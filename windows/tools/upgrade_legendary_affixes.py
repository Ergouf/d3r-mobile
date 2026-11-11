"""Extend the generated level-70 loadout from four to six max-tier affixes.

The loadout installed by generate_legendary_loadout.py carries one primary
stat, vitality, plus two situational affixes.  This tool keeps every item,
id, seed and slot unchanged and only rewrites ``base_affixes`` so each piece
also rolls critical damage / attack speed (weapon + jewelry) or a resistance
and life regeneration (armour).  A timestamped copy of the user directory is
written under local/saves before anything is replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D3EDIT = ROOT / "local/tools/d3edit-readonly-20261105"

SLOTS = {
    "head": 288, "chest": 304, "offhand": 320, "main": 336,
    "hands": 352, "belt": 368, "feet": 384, "shoulders": 400,
    "legs": 416, "wrists": 432, "ring2": 448, "ring1": 464,
    "neck": 480,
}
GENERATED_SLOTS = set(SLOTS.values())

STRENGTH = 1901866878          # X-X Strength 946-1,125
VITALITY = -620982138          # X-X Vitality 946-1,125
ARMOR = 82091320               # X-X Armor 559-595
LIFE_PER_HIT = 966857717       # X-X Life per Hit 3,514-4,457
CRIT_CHANCE = -1502864187      # X-X Critical Hit Chance 13-14%
CRIT_DAMAGE = 448428615        # X-X Critical Hit Damage 95-130%
ATTACK_SPEED = 996645142       # X-X Attack Speed 5-7%
PHYS_RESIST = -708791338       # X-X Physical Resistance 81-100
LIFE_PER_SECOND = -1931840200  # X-X Life per Second 868-1,185

JEWELRY = {SLOTS["ring1"], SLOTS["ring2"], SLOTS["neck"]}
WEAPONS = {SLOTS["main"], SLOTS["offhand"]}


def affixes_for(slot: int) -> list[int]:
    if slot in WEAPONS:
        return [STRENGTH, VITALITY, LIFE_PER_HIT, CRIT_CHANCE, CRIT_DAMAGE, ATTACK_SPEED]
    if slot in JEWELRY:
        return [STRENGTH, VITALITY, CRIT_DAMAGE, CRIT_CHANCE, ATTACK_SPEED, LIFE_PER_HIT]
    return [STRENGTH, VITALITY, ARMOR, CRIT_CHANCE, PHYS_RESIST, LIFE_PER_SECOND]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--directory", type=Path, required=True,
                    help="installed save user directory (heroes/*.dat live here)")
    ap.add_argument("--backup-root", type=Path,
                    default=ROOT / "local/saves")
    args = ap.parse_args()
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import D3Edit
    import Hero_pb2

    source = args.directory.resolve()
    heroes = sorted((source / "heroes").glob("*.dat"))
    if len(heroes) != 1:
        raise SystemExit(f"expected one hero file, found {len(heroes)}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = args.backup_root / f"kbm-maxgear-affix6-before-{stamp}"
    if backup.exists():
        raise SystemExit(f"backup already exists: {backup}")
    shutil.copytree(source, backup)

    hero_path = heroes[0]
    plain = D3Edit.decrypt_save(hero_path.read_bytes())
    hero = Hero_pb2.SavedDefinition()
    if hero.ParseFromString(plain) != len(plain) or not hero.IsInitialized():
        raise SystemExit("hero parse failed")

    changed = []
    for item in hero.items.items:
        if item.item_slot not in GENERATED_SLOTS:
            continue
        if item.generator.item_quality_level != 9:
            continue
        affixes = affixes_for(item.item_slot)
        gen = item.generator
        del gen.base_affixes[:]
        gen.base_affixes.extend(affixes)
        changed.append({"id": item.id.id_low, "slot": item.item_slot,
                        "gbid": gen.gb_handle.gbid, "affixes": list(gen.base_affixes)})
    if len(changed) != 13:
        raise SystemExit(f"expected 13 generated items, patched {len(changed)}")

    out_plain = hero.SerializeToString()
    out_raw = D3Edit.encrypt_save(out_plain)
    if D3Edit.decrypt_save(out_raw) != out_plain:
        raise SystemExit("encryption round trip failed")
    check = Hero_pb2.SavedDefinition()
    if (check.ParseFromString(out_plain) != len(out_plain) or not check.IsInitialized()
            or check.digest.level != 70):
        raise SystemExit("reloaded hero is invalid")
    hero_path.write_bytes(out_raw)

    manifest = {str(p.relative_to(backup)): sha(p) for p in backup.rglob("*") if p.is_file()}
    report = {
        "hero": str(hero_path),
        "hero_sha256": sha(hero_path),
        "backup": str(backup),
        "backup_manifest": manifest,
        "level": check.digest.level,
        "items_total": len(check.items.items),
        "patched": changed,
    }
    out_json = ROOT / "out/windows/kbm/session/maxgear-0060-affix6.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"patched": len(changed), "hero_sha256": report["hero_sha256"],
                      "backup": str(backup), "report": str(out_json)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
