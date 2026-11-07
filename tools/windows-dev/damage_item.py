"""Lower one item's durability in the installed save so a vendor repair has work.

Only the durability field of a single hero item is touched.  The D3Edit snapshot
is verified, a byte-exact no-op roundtrip is proven, and a cold copy of the save
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
HERO = "heroes/9af81ba794cf5b64.dat"


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fraction", type=float, default=0.25)
    ap.add_argument("--backup-name", default="kbm-repair-prep-20261105")
    ap.add_argument("--slot", type=int, default=-1, help="only items in this equipment slot")
    args = ap.parse_args()
    if not (0.05 <= args.fraction <= 0.9):
        ap.error("fraction must be within 0.05..0.9")

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

    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import Hero_pb2
    import D3Edit

    path = INSTALLED / HERO
    raw = path.read_bytes()
    plain = D3Edit.decrypt_save(raw)
    hero = Hero_pb2.SavedDefinition()
    if hero.ParseFromString(plain) != len(plain) or not hero.IsInitialized():
        raise RuntimeError("incomplete hero protobuf")
    if D3Edit.encrypt_save(plain) != raw or hero.SerializeToString() != plain:
        raise RuntimeError("no-op roundtrip is not byte exact")

    target = None
    for item in hero.items.items:
        gen = item.generator
        if args.slot >= 0 and item.item_slot != args.slot:
            continue
        if gen.max_durability > 0 and gen.durability >= gen.max_durability:
            target = item
            break
    if target is None:
        raise RuntimeError("no fully repaired item with durability found")
    gen = target.generator
    ident = (target.id.id_high, target.id.id_low)
    before = (gen.durability, gen.max_durability)
    gen.durability = max(1, int(gen.max_durability * args.fraction))

    encoded = hero.SerializeToString()
    check = Hero_pb2.SavedDefinition()
    if check.ParseFromString(encoded) != len(encoded) or not check.IsInitialized():
        raise RuntimeError("candidate does not decode")

    probe = Hero_pb2.SavedDefinition()
    probe.CopyFrom(check)
    for item in probe.items.items:
        if (item.id.id_high, item.id.id_low) == ident:
            item.generator.durability = before[0]
    if probe.SerializeToString() != plain:
        raise RuntimeError("a non-target field changed")

    path.write_bytes(D3Edit.encrypt_save(encoded))
    print(json.dumps({"backup": str(backup), "item_gbid": gen.gb_handle.gbid,
                      "durability": {"before": before[0], "after": gen.durability, "max": before[1]}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
