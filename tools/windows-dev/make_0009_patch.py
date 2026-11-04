"""Generate and register native world pointer patch 0009 after replaying 0001-0008."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "reference/ScarletNX-src"
PATCHES = ROOT / "patches/windows"
NAME = "0009-native-world-pointer.patch"
FILES = [
    "src/nx/CMakeLists.txt",
    "src/nx/runtime/native_input.c",
    "src/nx/runtime/native_world.c",
    "src/nx/runtime/native_world.h",
    "src/nx/runtime/platform/backend/sdl3.c",
]


def git(tree: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(tree), *args], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return result.stdout


def main() -> None:
    meta_path = PATCHES / "base.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    chain = [meta["patch"]] + [e["patch"] for e in meta.get("extra_patches", [])]
    if NAME in chain:
        chain = chain[:chain.index(NAME)]
    temp_root = Path(tempfile.gettempdir()).resolve()
    work = Path(tempfile.mkdtemp(prefix="snx-0009-", dir=temp_root)).resolve()
    tree = work / "tree"
    added = False
    try:
        git(SRC, "worktree", "add", "--detach", str(tree), meta["base_commit"])
        added = True
        git(tree, "config", "core.autocrlf", "false")
        for name in chain:
            git(tree, "apply", "--whitespace=nowarn", str(PATCHES / name))
        git(tree, "add", "-A")
        git(tree, "-c", "user.email=snx@local", "-c", "user.name=snx", "commit",
            "-m", "intermediate 0001-0008")
        hashes = {}
        for rel in FILES:
            data = (SRC / rel).read_bytes().replace(b"\r\n", b"\n")
            (tree / rel).write_bytes(data)
            hashes[rel] = hashlib.sha256(data).hexdigest()
        git(tree, "add", "--intent-to-add", "--", *FILES)
        diff = git(tree, "diff", "--", *FILES)
        if not diff.strip():
            raise RuntimeError("empty patch")
        patch = PATCHES / NAME
        patch.write_text(diff, encoding="utf-8", newline="\n")
        entry = {"patch": NAME, "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
                 "changed_files_lf_sha256": hashes}
        meta["extra_patches"] = [e for e in meta.get("extra_patches", []) if e["patch"] != NAME] + [entry]
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(entry, indent=2))
    finally:
        # Resolve and validate every recursive removal target before cleanup.
        if work.parent != temp_root or not work.name.startswith("snx-0009-"):
            raise RuntimeError("unsafe temporary worktree path")
        if tree.resolve().parent != work:
            raise RuntimeError("worktree escaped temporary directory")
        if added:
            git(SRC, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
