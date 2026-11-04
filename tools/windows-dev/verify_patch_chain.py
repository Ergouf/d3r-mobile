#!/usr/bin/env python3
"""Replay the Windows source patches on a fresh checkout and verify every stage.

`Apply-Patches.ps1 -CheckOnly` only proves the last patch reverses; it returns
early and never checks that the chain rebuilds. This script builds the chain
for real: a detached git worktree at base.json's base commit, the patches
applied in order with plain `git apply`, and each patch's changed files
compared to the LF-normalised SHA-256 that base.json records for that stage.

Usage:
  python tools/windows-dev/verify_patch_chain.py [--source reference/ScarletNX-src] [--keep]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PATCHES = ROOT / "patches/windows"


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def lf_hash(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(ROOT / "reference/ScarletNX-src"))
    ap.add_argument("--keep", action="store_true", help="leave the worktree in place")
    args = ap.parse_args()

    source = Path(args.source).resolve()
    meta = json.loads((PATCHES / "base.json").read_text(encoding="utf-8"))
    chain = [{"patch": meta["patch"], "patch_sha256": meta["patch_sha256"],
              "files": meta["changed_files_lf_sha256"]}]
    for entry in meta.get("extra_patches", []):
        chain.append({"patch": entry["patch"], "patch_sha256": entry["patch_sha256"],
                      "files": entry["changed_files_lf_sha256"]})

    work = Path(tempfile.mkdtemp(prefix="snx-patch-check-"))
    worktree = work / "tree"
    add = run(["git", "-C", str(source), "worktree", "add", "--detach", str(worktree), meta["base_commit"]])
    if add.returncode != 0:
        print("worktree add failed:\n" + add.stderr)
        return 2
    failures = 0
    try:
        run(["git", "-C", str(worktree), "config", "core.autocrlf", "false"])
        for entry in chain:
            patch = PATCHES / entry["patch"]
            sha = hashlib.sha256(patch.read_bytes()).hexdigest()
            if sha != entry["patch_sha256"]:
                print(f"FAIL {entry['patch']}: sha256 {sha[:12]} != recorded {entry['patch_sha256'][:12]}")
                failures += 1
                continue
            applied = run(["git", "-C", str(worktree), "apply", "--ignore-whitespace", "--whitespace=nowarn",
                           str(patch)])
            if applied.returncode != 0:
                print(f"FAIL {entry['patch']}: does not apply\n{applied.stderr.strip()}")
                failures += 1
                break
            stage_bad = 0
            for rel, want in entry["files"].items():
                path = worktree / rel
                if not path.exists():
                    print(f"  missing {rel}")
                    stage_bad += 1
                    continue
                got = lf_hash(path.read_bytes())
                if got != want:
                    print(f"  {rel}: {got[:12]} != {want[:12]}")
                    stage_bad += 1
            if stage_bad:
                print(f"FAIL {entry['patch']}: {stage_bad} file(s) differ from the recorded result")
                failures += 1
                break
            print(f"ok   {entry['patch']}: applies and its {len(entry['files'])} file(s) match")
    finally:
        if args.keep:
            print("worktree kept at", worktree)
        else:
            run(["git", "-C", str(source), "worktree", "remove", "--force", str(worktree)])
            shutil.rmtree(work, ignore_errors=True)
    print("PASS" if failures == 0 else f"FAIL ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
