"""Generate patches/windows/0020-native-actor-attack.patch from the live tree.

Replays 0001-0019 on a detached worktree at base.json's base commit, commits that
intermediate state, copies the files this round changed from reference/ScarletNX-src,
and writes the resulting diff as 0020.
"""
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
NAME = "0020-native-actor-attack.patch"
FILES = [
    "src/nx/runtime/native_world.c",
]


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def lf_hash(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    meta = json.loads((PATCHES / "base.json").read_text(encoding="utf-8"))
    chain = [meta["patch"]] + [e["patch"] for e in meta.get("extra_patches", [])]
    if NAME in chain:
        chain = chain[:chain.index(NAME)]
    work = Path(tempfile.mkdtemp(prefix="snx-0020-"))
    tree = work / "tree"
    add = run(["git", "-C", str(SRC), "worktree", "add", "--detach", str(tree), meta["base_commit"]])
    if add.returncode != 0:
        print("worktree add failed:\n" + add.stderr)
        return 2
    try:
        run(["git", "-C", str(tree), "config", "core.autocrlf", "false"])
        for name in chain:
            applied = run(["git", "-C", str(tree), "apply", "--ignore-whitespace", "--whitespace=nowarn",
                           str(PATCHES / name)])
            if applied.returncode != 0:
                print(f"{name} failed:\n{applied.stderr}")
                return 3
        run(["git", "-C", str(tree), "add", "-A"])
        commit = run(["git", "-C", str(tree), "-c", "user.email=snx@local", "-c", "user.name=snx",
                      "commit", "-m", "intermediate 0001-0019"])
        if commit.returncode != 0:
            print("commit failed:\n" + commit.stderr)
            return 4
        for rel in FILES:
            shutil.copyfile(SRC / rel, tree / rel)
        diff = run(["git", "-C", str(tree), "diff", "--"] + FILES)
        if diff.returncode != 0 or not diff.stdout.strip():
            print("empty or failed diff:\n" + diff.stdout + diff.stderr)
            return 5
        out = PATCHES / NAME
        out.write_bytes(diff.stdout.replace("\r\n", "\n").encode("utf-8"))
        print("patch", out, "sha256", hashlib.sha256(out.read_bytes()).hexdigest())
        for rel in FILES:
            print(rel, lf_hash((tree / rel).read_bytes()))
    finally:
        if tree.resolve().parent != work.resolve() or work.resolve().parent != Path(tempfile.gettempdir()).resolve() or not work.name.startswith("snx-0020-"):
            raise RuntimeError("refusing cleanup outside this task temp directory")
        run(["git", "-C", str(SRC), "worktree", "remove", "--force", str(tree)])
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
