"""Repackage verified assets with the tested FSR runtime, then extract and verify every file."""

import argparse
import copy
from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import tarfile
import time
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PREFIX = "DiabloIII-Windows/"
GAME = "01001B300B9BE000/"
BASE_COMMIT = "dbf8915965367e8a9616b19e5a0c1eddafaf28f3"
CHUNK = 8 * 1024 * 1024


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe archive path: {name}")
    lower = name.lower()
    if any(s in p.parts for s in (".git", "shader_cache", "captures", "__pycache__")):
        raise ValueError(f"Unwanted directory: {name}")
    if lower.endswith((".xci", ".nca", ".keys", ".log", ".pid", ".jitcache", ".orig")):
        raise ValueError(f"Unwanted file: {name}")
    return p


def source_snapshot(dest):
    source = ROOT / "windows/source/ScarletNX-src"
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode("utf-8").split("\0")
    names += [
        "src/nx/gpu/vk/fsr.c", "src/nx/gpu/vk/fsr_spv.h",
        "src/nx/gpu/vk/shaders/fsr.vert", "src/nx/gpu/vk/shaders/fsr.frag",
        "src/nx/gpu/vk/shaders/fsr_rcas.frag",
    ]
    names = sorted(set(n for n in names if n))
    with tarfile.open(dest, "w:gz", compresslevel=6) as tar:
        for name in names:
            safe_name(name)
            path = source / name
            if not path.is_file():
                raise ValueError(f"Missing source file: {path}")
            tar.add(path, arcname="ScarletNX-FSR1/windows/source/ScarletNX-src/" + name, recursive=False)
        for name in ("Activate.ps1", "Build.ps1", "build.sh", "README.md", "Test-Dependencies.ps1", "vulkan-smoke.c", "smoke.comp", "Install-Release.ps1", "package_fsr_release.py"):
            tar.add(ROOT / "windows/tools" / name,
                    arcname="ScarletNX-FSR1/windows/tools/" + name, recursive=False)
        tar.add(ROOT / "licenses/AMD-FSR1-LICENSE.txt",
                arcname="ScarletNX-FSR1/licenses/AMD-FSR1-LICENSE.txt", recursive=False)
        for name in (".gitattributes", "base.json", "0001-fsr1-easu-rcas.patch", "Apply-Patches.ps1", "README.md"):
            tar.add(ROOT / "windows/patches" / name,
                    arcname="ScarletNX-FSR1/windows/patches/" + name, recursive=False)
    return {"tracked_and_fsr_files": len(names), "sha256": sha_file(dest), "bytes": dest.stat().st_size}


def remove_extra(extra, field):
    result = bytearray()
    offset = 0
    while offset + 4 <= len(extra):
        tag, size = struct.unpack_from("<HH", extra, offset)
        end = offset + 4 + size
        if end > len(extra):
            raise ValueError("Malformed ZIP extra field")
        if tag != field:
            result += extra[offset:end]
        offset = end
    if offset != len(extra):
        raise ValueError("Trailing ZIP extra bytes")
    return bytes(result)


def copy_raw_member(source_file, out, info, end):
    """Keep the original compressed data and CRC; ZipFile rewrites its central-directory offset."""
    if info.flag_bits & 1:
        raise ValueError("Encrypted source members are not supported")
    saved = copy.copy(info)
    saved.extra = remove_extra(saved.extra, 1)  # Central ZIP64 offsets/sizes must be generated anew.
    saved.header_offset = out.fp.tell()
    out._writecheck(saved)
    out._didModify = True
    source_file.seek(info.header_offset)
    remaining = end - info.header_offset
    if remaining <= 0:
        raise ValueError(f"Invalid source member extent: {info.filename}")
    while remaining:
        block = source_file.read(min(CHUNK, remaining))
        if not block:
            raise EOFError(info.filename)
        out.fp.write(block)
        remaining -= len(block)
    out.filelist.append(saved)
    out.NameToInfo[saved.filename] = saved
    out.start_dir = out.fp.tell()


def test_raw_copy():
    # Include a streaming data descriptor and a forced ZIP64 local header in this structural check.
    class Unseekable(io.BytesIO):
        def seekable(self):
            return False

        def seek(self, *args):
            raise io.UnsupportedOperation()

    original = Unseekable()
    with zipfile.ZipFile(original, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("one.txt", b"first" * 100)
        with z.open("two.txt", "w", force_zip64=True) as f:
            f.write(b"second" * 100)
    raw = original.getvalue()
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as z, zipfile.ZipFile(rebuilt, "w") as out:
        infos = sorted(z.infolist(), key=lambda i: i.header_offset)
        for n, info in enumerate(infos):
            end = infos[n + 1].header_offset if n + 1 < len(infos) else z.start_dir
            copy_raw_member(io.BytesIO(raw), out, info, end)
        out.writestr("new.txt", b"new")
    with zipfile.ZipFile(rebuilt) as z:
        assert z.read("one.txt") == b"first" * 100
        assert z.read("two.txt") == b"second" * 100
        assert z.read("new.txt") == b"new"
        assert z.testzip() is None


def release_settings(text):
    """Update keys in their own sections, preserving comments and unknown settings."""
    wanted = {
        "Display": {"fullscreen": "1", "language": "15"},
        "Graphics": {"resolution": "1", "upscaler": "1", "shadows": "1", "vsync": "1", "async_pipelines": "0"},
        "Performance": {"fps_limit": "game"},
        "Controllers": {"gamepad_swap_ab": "1", "gamepad_map": "west:X north:Y"},
        "Network": {"network": "0", "ldn": "off"},
        "Debug": {"vk_validation": "0", "profile": "0", "diag": "0"},
    }
    updates = {s.casefold(): (s, {k.casefold(): (k, v) for k, v in values.items()}) for s, values in wanted.items()}
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    out, section, seen_sections, seen_keys = [], None, set(), {}

    def flush():
        if section in updates:
            for lower, (key, value) in updates[section][1].items():
                if lower not in seen_keys[section]:
                    out.append(f"{key}={value}")
                    seen_keys[section].add(lower)

    for line in lines:
        heading = re.fullmatch(r"\s*\[([^\]]+)\]\s*(?:[;#].*)?", line)
        if heading:
            flush()
            section = heading[1].strip().casefold()
            if section in seen_sections:
                raise ValueError(f"Duplicate INI section: {heading[1]}")
            seen_sections.add(section)
            seen_keys[section] = set()
            out.append(line)
            continue
        item = re.match(r"\s*([^;#\s=][^=]*)=", line)
        key = item[1].strip().casefold() if item else None
        if section in updates and key in updates[section][1]:
            if key in seen_keys[section]:
                continue  # Collapse duplicate managed keys from an older repack.
            seen_keys[section].add(key)
            name, value = updates[section][1][key]
            out.append(f"{name}={value}")
        else:
            out.append(line)
    flush()
    for lower, (name, values) in updates.items():
        if lower not in seen_sections:
            out += ["", f"[{name}]"] + [f"{key}={value}" for key, value in values.values()]
    return "\r\n".join(out) + "\r\n"


def test_settings():
    old = "[Display]\nfullscreen=0\nlanguage=1\n[Graphics]\nresolution=1\n; retain this comment\nshadows=1\n[Other]\nupscaler=custom\n"
    new = release_settings(old)
    assert release_settings(new) == new
    assert "fullscreen=1\r\n" in new
    assert "upscaler=1\r\n" in new and new.count("upscaler=1\r\n") == 1
    assert "[Other]\r\nupscaler=custom" in new
    assert "; retain this comment" in new
    duplicate = "[Graphics]\nupscaler=0\nupscaler=1\nresolution=1\n"
    assert release_settings(duplicate).count("upscaler=1\r\n") == 1
    assert release_settings("") == release_settings(release_settings(""))


def publish_verified(partial, output, expected_hash, attempts=4):
    """Publish only a verified archive; never overwrite a pre-existing destination."""
    for attempt in range(attempts):
        if output.exists():
            raise FileExistsError(output)
        try:
            # os.rename on Windows fails if the destination already exists.
            if os.name == "nt":
                partial.rename(output)
            else:
                os.link(partial, output)
                partial.unlink()
            return {"mode": "rename", "staging_preserved": False}
        except PermissionError as error:
            if getattr(error, "winerror", None) not in (32, 33):
                raise
            if attempt + 1 < attempts:
                time.sleep(0.5)
    print("Staging is held by another process; copying the verified file without stopping it", flush=True)
    if shutil.disk_usage(output.parent).free < partial.stat().st_size:
        raise RuntimeError("Insufficient extra space for publication by copy; verified staging was preserved")
    with open(partial, "rb") as source, open(output, "xb") as target:
        shutil.copyfileobj(source, target, CHUNK)
        target.flush()
        os.fsync(target.fileno())
    if sha_file(output) != expected_hash:
        raise ValueError("Published copy SHA-256 mismatch; source staging was preserved")
    return {"mode": "copy", "staging_preserved": True}


def test_publication():
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory(prefix="diablo-package-test-") as folder:
        root = Path(folder)
        staged, target = root / "first.partial.zip", root / "first.zip"
        staged.write_bytes(b"verified test archive")
        want = sha_file(staged)
        result = publish_verified(staged, target, want)
        assert result["mode"] == "rename" and not staged.exists()
        assert sha_file(target) == want
        blocked = root / "blocked.partial.zip"
        blocked.write_bytes(b"do not overwrite")
        try:
            publish_verified(blocked, target, sha_file(blocked))
        except FileExistsError:
            pass
        else:
            raise AssertionError("Existing archive was not protected")
        assert sha_file(target) == want and blocked.read_bytes() == b"do not overwrite"
        locked, copied = root / "locked.partial.zip", root / "copied.zip"
        locked.write_bytes(b"verified copy fallback")
        expected = sha_file(locked)
        lock = PermissionError("Sharing violation in test")
        lock.winerror = 32
        with patch.object(Path, "rename", side_effect=lock), patch("os.name", "nt"):
            # Existing Path objects remain native; no Windows path is constructed by the tested function.
            result = publish_verified(locked, copied, expected, attempts=1)
        assert result == {"mode": "copy", "staging_preserved": True}
        assert locked.exists() and sha_file(copied) == expected


README = """# 暗黑破坏神 III Windows FSR1 运行包

完整解压后双击 `Launch.cmd`。保持目录结构完整，不要在压缩软件内直接运行。

- Windows x64，需要支持 Vulkan 1.3 的显卡及正常驱动。无需安装 Clang、MSYS2 或 Vulkan SDK 即可游玩。
- 本版默认全屏、FSR1 EASU 放大及较弱 RCAS 锐化。内部保持原生 1×、阴影开启；RCAS 衰减为 1.5 stops，数值越大锐化越弱。
- 本机验证使用 Intel Arc、Vulkan 1.3.293；3072×1920 屏幕中保持游戏纵横比，FSR 输出 3072×1728。
- FSR1 改善最终放大清晰度，不做帧生成。显示器 120Hz 不代表游戏已经输出 120 个不同帧；本版没有新的实战 FPS 测量结论。
- Xbox 手柄：A 确认、B 取消/返回，X→游戏 X、Y→游戏 Y。`gamepad_swap_ab=1`，`gamepad_map=west:X north:Y`；游戏需在前台。
- 简体中文，包含中文语音 DLC `01001b300b9bf00b.romfs`，5,609,751,868 bytes。运行时已识别该 DLC；完整声音听验尚未完成，可在游戏内选择语音语言。
- 保留原包制作时的存档。路径为 `01001B300B9BE000/01001B300B9BE000_data/save/`，换包前请备份自己正在使用的整个 save 目录。
- 默认离线：`network=0`、`ldn=off`。验证层、性能分析和 shader captures 默认关闭。
- 不包含日志、JIT/着色器缓存、测试图片、原始 XCI/NCA 或密钥。首次遇到新内容时需要生成缓存。

快捷键：F11 / Alt+Enter 切换全屏，F2 打开运行时菜单，Escape 退出程序。键盘 Space/X 对应游戏 A，Z 对应 B。

## 构建与来源

ScarletNX 基于提交 `dbf8915965367e8a9616b19e5a0c1eddafaf28f3`，包含本地 FSR1、描述符录制兼容、资源延迟回收及回退布局修复，使用 MSYS2 CLANG64 构建入口，不能视为未修改的官方 nightly。

上游：https://github.com/scarletnx/ScarletNX

游戏 Title ID `01001B300B9BE000`，版本 `2.7.7.92380`；更新 main NSO BuildID `2607A74F5DF7754CC0357B5DF7E496931355D8CA`。游戏内容来自用户工作区已有资料。

运行时程序 SHA-256：`@RUNTIME_SHA256@`。

本包以已保留的游戏资源包为基线，重新装入所选运行时。运行时身份、源码快照和校验结果在随包 BUILD-INFO.json 与包外校验报告中；重新打包本身不代表新增实战测试通过。

上游及第三方许可在 `licenses/`，AMD FSR1 的 MIT 许可在 `licenses/AMD-FSR1-LICENSE.txt`。修改后的 ScarletNX 源码快照、固定依赖下载配置和构建说明在 `sources/ScarletNX-FSR1-source.tar.gz`；无需解压源码即可运行游戏。

## 校验

`SHA256SUMS.txt` 覆盖除清单本身之外的所有文件。ZIP 旁的 `.sha256` 文件校验整个压缩包。运行后配置、存档和缓存可能发生变化。
"""


def build(args):
    test_raw_copy()
    test_settings()
    if args.source is None:
        raise ValueError(
            "A baseline ZIP is required: pass --source or set DIABLO_RELEASE_ZIP; "
            "the local/releases copy was removed as a duplicate of the installed game"
        )
    old = args.source.resolve()
    if not old.is_file():
        raise FileNotFoundError(f"Baseline ZIP not found: {old}")
    output = args.output.resolve()
    partial = output.with_name(output.stem + ".partial.zip")
    evidence = args.evidence.resolve()
    extracted = evidence / "extracted"
    evidence.mkdir(parents=True, exist_ok=True)
    if output == old:
        raise ValueError("The output must not replace the baseline archive")
    if output.exists() or partial.exists() or (args.extract and extracted.exists()):
        raise FileExistsError("Output, partial archive or extraction directory already exists")
    if output.with_name(output.name + ".sha256").exists():
        raise FileExistsError("Output checksum already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    required_space = old.stat().st_size * (2 if args.extract else 1) + 2 * 1024**3
    if shutil.disk_usage(output.parent).free < required_space:
        raise RuntimeError("Insufficient free space for the ZIP and requested verification")
    exe = args.runtime.resolve()
    runtime_hash = sha_file(exe)
    if args.expected_runtime_sha256 and runtime_hash != args.expected_runtime_sha256.lower():
        raise ValueError("Runtime differs from --expected-runtime-sha256")
    snapshot = evidence / "ScarletNX-FSR1-source.tar.gz"
    source_info = source_snapshot(snapshot)
    print(f"Source snapshot ready: {source_info['bytes']:,} bytes", flush=True)
    t0 = time.monotonic()
    with zipfile.ZipFile(old) as original:
        infos = sorted(original.infolist(), key=lambda i: i.header_offset)
        if len(infos) != len({i.filename for i in infos}):
            raise ValueError("Duplicate names in the source archive")
        manifest = {}
        for line in original.read(PREFIX + "SHA256SUMS.txt").decode("utf-8-sig").splitlines():
            if line:
                digest, name = line.split("  ", 1)
                safe_name(name)
                if name in manifest or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                    raise ValueError(f"Duplicate name or invalid hash in the original manifest: {name}")
                manifest[name] = digest.lower()
        expected_names = {PREFIX + n for n in manifest} | {PREFIX + "SHA256SUMS.txt"}
        if expected_names != {i.filename for i in infos}:
            raise ValueError("Original manifest and archive disagree")
        ini = original.read(PREFIX + GAME + "01001B300B9BE000.ini").decode("utf-8-sig")
        ini = release_settings(ini).encode("utf-8")
        amd_license = (ROOT / "licenses/AMD-FSR1-LICENSE.txt").read_text(encoding="utf-8")
        replacements = {
            GAME + "01001B300B9BE000.exe": exe,
            GAME + "01001B300B9BE000.ini": ini,
            "README.zh-CN.md": README.replace("@RUNTIME_SHA256@", runtime_hash).encode("utf-8"),
            "Launch.cmd": b'@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n"%~dp001001B300B9BE000\\01001B300B9BE000.exe"\r\nendlocal\r\n',
            "licenses/AMD-FSR1-LICENSE.txt": amd_license.encode("utf-8"),
            "sources/ScarletNX-FSR1-source.tar.gz": snapshot,
            "sources/README.zh-CN.md": ("# 本地修改版源码\n\n"
                "解开 ScarletNX-FSR1-source.tar.gz，得到 ScarletNX-FSR1 目录，保留其内部目录布局。\n"
                "安装 MSYS2 CLANG64 所需依赖后，在 ScarletNX-FSR1 目录内运行：\n\n"
                "```powershell\n"
                ".\\tools\\windows-dev\\Build.ps1 -Configure\n"
                "```\n\n"
                "MSYS2 默认路径为 D:\\workspace\\msys2\\msys64；可用 -MsysRoot 指定其他安装路径。"
                "依赖包列表与配置步骤在 windows/source/ScarletNX-src/docs/BUILD.md 的 Windows / MSYS2 CLANG64 一节。"
                "CPM 与各依赖版本及下载地址由 cmake 配置固定；首次构建需联网获取。\n\n"
                "源码保留上游许可证，包含本地 FSR1 EASU/RCAS、布局与资源寿命修复。"
                "AMD 原始算法参考：https://github.com/GPUOpen-Effects/FidelityFX-FSR 。\n"
                "普通游玩不需要构建或安装这些开发依赖。\n").encode("utf-8"),
            "sources/BUILD-INFO.json": (json.dumps({
                "base_commit": BASE_COMMIT, "runtime_sha256": runtime_hash,
                "build_toolchain": "MSYS2 CLANG64; see the matching build environment and runtime SHA-256",
                "source_snapshot": source_info, "internal_resolution": 1,
                "fsr": "FSR1 EASU + RCAS (1.5 stops attenuation)", "frame_generation": False,
            }, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        }
        with open(old, "rb") as source_raw, zipfile.ZipFile(partial, "x", allowZip64=True) as out:
            last_progress = time.monotonic()
            for n, info in enumerate(infos):
                name = info.filename
                if not name.startswith(PREFIX):
                    raise ValueError(name)
                rel = name[len(PREFIX):]
                safe_name(rel)
                if rel in replacements or rel == "SHA256SUMS.txt":
                    continue
                end_offset = infos[n + 1].header_offset if n + 1 < len(infos) else original.start_dir
                copy_raw_member(source_raw, out, info, end_offset)
                if time.monotonic() - last_progress >= 10:
                    print(f"Packing: {out.fp.tell()/1024**3:.2f} GiB written", flush=True)
                    last_progress = time.monotonic()
            for name, content in replacements.items():
                safe_name(name)
                if isinstance(content, Path):
                    digest = sha_file(content)
                    out.write(content, PREFIX + name, compress_type=zipfile.ZIP_STORED if name.endswith(".gz") else zipfile.ZIP_DEFLATED, compresslevel=6)
                else:
                    digest = hashlib.sha256(content).hexdigest()
                    out.writestr(PREFIX + name, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
                manifest[name] = digest
            text = "".join(f"{manifest[n]}  {n}\n" for n in sorted(manifest))
            out.writestr(PREFIX + "SHA256SUMS.txt", text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    print(f"ZIP written ({partial.stat().st_size:,} bytes); verifying every member", flush=True)
    # ZipExtFile checks each CRC at EOF; SHA-256 is checked in the same full read.
    if args.extract:
        extracted.mkdir()
    total_bytes = 0
    verified = 0
    last_progress = time.monotonic()
    with zipfile.ZipFile(partial) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("Duplicate names in rebuilt archive")
        if set(z.namelist()) != {PREFIX + n for n in manifest} | {PREFIX + "SHA256SUMS.txt"}:
            raise ValueError("Rebuilt manifest and archive disagree")
        for info in z.infolist():
            rel = info.filename[len(PREFIX):]
            safe_name(rel)
            target = extracted.joinpath(*PurePosixPath(info.filename).parts) if args.extract else None
            if target:
                target.resolve().relative_to(extracted.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with z.open(info) as stream, (open(target, "xb") if target else nullcontext()) as dest:
                while block := stream.read(CHUNK):
                    if dest:
                        dest.write(block)
                    h.update(block)
                    total_bytes += len(block)
            if rel != "SHA256SUMS.txt" and h.hexdigest() != manifest[rel]:
                raise ValueError(f"SHA-256 mismatch: {rel}")
            verified += 1
            if time.monotonic() - last_progress >= 10:
                print(f"Verified CRC + SHA-256: {verified}/{len(z.infolist())} entries, {total_bytes/1024**3:.2f} GiB", flush=True)
                last_progress = time.monotonic()
    print("All file hashes and CRCs passed; calculating archive SHA-256", flush=True)
    archive_hash = sha_file(partial)
    (evidence / 'verified-staging.json').write_text(json.dumps({
        'path': str(partial), 'sha256': archive_hash, 'entries': verified,
        'manifest_files': len(manifest), 'all_file_hashes_and_crc_passed': True,
    }, indent=2) + '\n', encoding='utf-8')
    report = {
        "zip": str(output), "staging_zip": str(partial), "zip_bytes": partial.stat().st_size, "zip_sha256": archive_hash,
        "entries": verified, "manifest_files": len(manifest), "verified_ok": True,
        "crc_test": "all entries read to EOF; CRC passed", "hash_mismatches": [],
        "extracted_root": str(extracted / PREFIX.rstrip("/")) if args.extract else None,
        "runtime_sha256": runtime_hash, "settings": {"upscaler": 1, "resolution": 1, "shadows": 1, "fullscreen": 1, "language": 15},
        "source_snapshot": source_info, "release_published": False,
    }
    report_path = evidence / "zip-validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        report["publication"] = publish_verified(partial, output, archive_hash)
        sha_path = output.with_name(output.name + ".sha256")
        with sha_path.open("x", encoding="ascii") as checksum:
            checksum.write(archive_hash + "  " + output.name + "\n")
        report["release_published"] = True
    except Exception as error:
        report["publication_error"] = str(error)
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - t0, 2)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.environ["DIABLO_RELEASE_ZIP"]) if os.environ.get("DIABLO_RELEASE_ZIP") else None,
        help="Verified baseline ZIP, or set DIABLO_RELEASE_ZIP; no default archive is retained in the workspace",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "out/windows/releases/DiabloIII-Windows-2.7.7.92380-zhCN-Xbox-FSR1-repacked.zip")
    parser.add_argument("--evidence", type=Path, default=ROOT / "out/windows/packages")
    parser.add_argument("--runtime", type=Path, default=ROOT / "out/windows/build/scarletnx.exe")
    parser.add_argument("--expected-runtime-sha256", help="Optional SHA-256 identity of an already tested runtime")
    parser.add_argument("--extract", action="store_true", help="Also write a full test extraction under the evidence directory")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        test_raw_copy()
        test_settings()
        test_publication()
        print("Raw ZIP64 copy, idempotent INI settings and protected publication tests passed")
    else:
        build(args)
