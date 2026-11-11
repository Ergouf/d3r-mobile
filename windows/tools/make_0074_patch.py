"""Generate the pending-acceptance map, portal and footer fix after patch 0073."""
from __future__ import annotations

import difflib
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "windows/source/ScarletNX-src"
PATCHES = ROOT / "windows/patches"
NAME = "0074-native-map-portals-footer.patch"
FILES = ("src/nx/runtime/native_world.c",)


def command(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)


def normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=NAME)
    parser.add_argument("--after", default="0073-native-skillbar-labels.patch")
    parser.add_argument("--files", nargs="+", default=FILES)
    arguments = parser.parse_args()
    patch_name = arguments.name
    if Path(patch_name).name != patch_name or not patch_name.endswith(".patch"):
        raise SystemExit("patch name must be a basename ending in .patch")
    metadata_path = PATCHES / "base.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    chain = [metadata["patch"], *(entry["patch"] for entry in metadata["extra_patches"])]
    if patch_name in chain:
        if chain[-1] != patch_name:
            raise SystemExit("cannot replace a patch that already has follow-up patches")
        chain = chain[:chain.index(patch_name)]
    if chain[-1] != arguments.after:
        raise SystemExit(f"expected {arguments.after} immediately before this patch")
    temporary = Path(tempfile.mkdtemp(prefix="snx-0074-", dir=ROOT / "out")).resolve()
    tree = temporary / "tree"
    command(["git", "-C", str(SOURCE), "worktree", "add", "--detach", str(tree), metadata["base_commit"]])
    try:
        command(["git", "-C", str(tree), "config", "core.autocrlf", "false"])
        for name in chain:
            command(["git", "-C", str(tree), "apply", "--ignore-whitespace", "--whitespace=nowarn", str(PATCHES / name)])
        fragments = []
        hashes = {}
        for relative in arguments.files:
            if not (SOURCE / relative).resolve().is_relative_to(SOURCE.resolve()):
                raise SystemExit("source file is outside the source tree")
            before, after = normalized(tree / relative), normalized(SOURCE / relative)
            if before == after:
                continue
            fragments.append(f"diff --git a/{relative} b/{relative}\n")
            fragments.extend(difflib.unified_diff(
                before.decode("utf-8").splitlines(keepends=True),
                after.decode("utf-8").splitlines(keepends=True),
                fromfile=f"a/{relative}", tofile=f"b/{relative}",
            ))
            hashes[relative] = hashlib.sha256(after).hexdigest()
        if not fragments:
            raise SystemExit("no changes to register")
        patch = "".join(fragments).encode("utf-8")
        (PATCHES / patch_name).write_bytes(patch)
        entry = {"patch": patch_name, "patch_sha256": hashlib.sha256(patch).hexdigest(), "changed_files_lf_sha256": hashes}
        metadata["extra_patches"] = [previous for previous in metadata["extra_patches"] if previous["patch"] != patch_name] + [entry]
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(entry, indent=2))
    finally:
        if not tree.resolve().is_relative_to((ROOT / "out").resolve()):
            raise RuntimeError("temporary worktree is outside the build workspace")
        command(["git", "-C", str(SOURCE), "worktree", "remove", "--force", str(tree)])
        temporary.rmdir()


if __name__ == "__main__":
    main()
