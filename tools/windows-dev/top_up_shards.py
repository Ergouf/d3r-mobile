"""Raise the blood-shard balance of the installed save in place (local-only).

Only currency id 1 is modified.  The tool verifies the D3Edit snapshot, decodes
the account, proves a byte-exact no-op roundtrip, rewrites the single field,
and proves every other protobuf field is unchanged.  A cold copy of the save
directory is kept under local/saves/ before the write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D3EDIT = ROOT / "local/tools/d3edit-clean"
PROVENANCE = ROOT / "local/tools/d3edit-source-provenance.json"
INSTALLED = Path(r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000_data\save\user.0123456789abcdeffedcba9876543210")


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shards", type=int, default=500)
    ap.add_argument("--backup-name", default="kbm-shards-topup-20261105")
    args = ap.parse_args()
    if not (0 <= args.shards <= 500):
        ap.error("shards must be within 0..500")

    prov = json.loads(PROVENANCE.read_text("utf-8"))
    for rel, want in prov["file_sha256"].items():
        if digest(D3EDIT / rel) != want:
            raise RuntimeError("D3Edit snapshot changed: " + rel)
    if subprocess.check_output(["git", "-C", str(D3EDIT), "status", "--porcelain"]):
        raise RuntimeError("D3Edit checkout is not clean")

    backup = ROOT / "local/saves" / args.backup_name
    if backup.exists():
        raise FileExistsError("backup folder already exists: " + str(backup))
    shutil.copytree(INSTALLED, backup)
    before_files = {str(p.relative_to(INSTALLED)): digest(p) for p in INSTALLED.rglob("*") if p.is_file()}
    after_backup = {str(p.relative_to(backup)): digest(p) for p in backup.rglob("*") if p.is_file()}
    if before_files != after_backup:
        raise RuntimeError("backup copy does not match the installed save")

    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import Account_pb2
    import D3Edit

    target = INSTALLED / "account.dat"
    raw = target.read_bytes()
    plain = D3Edit.decrypt_save(raw)
    account = Account_pb2.SavedDefinition()
    if account.ParseFromString(plain) != len(plain) or not account.IsInitialized():
        raise RuntimeError("incomplete account protobuf")
    if D3Edit.encrypt_save(plain) != raw or account.SerializeToString() != plain:
        raise RuntimeError("no-op roundtrip is not byte exact")
    part = next(p for p in account.partitions if p.partition_id == 0)
    currency = next(c for c in part.currency_data.currency if c.id == 1)
    before = currency.count
    currency.count = args.shards
    encoded = account.SerializeToString()
    check = Account_pb2.SavedDefinition()
    if check.ParseFromString(encoded) != len(encoded) or not check.IsInitialized():
        raise RuntimeError("candidate does not decode")
    new_count = next(c.count for c in next(p for p in check.partitions if p.partition_id == 0).currency_data.currency
                     if c.id == 1)
    if new_count != args.shards:
        raise RuntimeError("currency update mismatch")
    currency.count = before
    if account.SerializeToString() != plain:
        raise RuntimeError("a non-target protobuf field changed")

    currency.count = args.shards
    target.write_bytes(D3Edit.encrypt_save(account.SerializeToString()))
    print(json.dumps({"backup": str(backup), "blood_shards": {"before": before, "after": args.shards},
                      "optimized": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
