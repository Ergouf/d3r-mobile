"""Generate a deterministic level-70 Crusader loadout in a copied save.

The source save is copied first. Existing equipped items are moved to free
inventory squares so the replacement remains reversible at item level.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
D3EDIT = ROOT / "local/tools/d3edit-readonly-20261105"
GBIDS = D3EDIT / "assets/gbids.json"
PROVENANCE = ROOT / "local/tools/d3edit-source-provenance.json"

# Game item slots in this save format.
SLOTS = {
    "head": 288, "chest": 304, "offhand": 320, "main": 336,
    "hands": 352, "belt": 368, "feet": 384, "shoulders": 400,
    "legs": 416, "wrists": 432, "ring2": 448, "ring1": 464,
    "neck": 480,
}
GEAR_SLOTS = set(SLOTS.values())
INVENTORY = 272

LOADOUT = [
    ("Akkhan helm", "head", -1992164625),
    ("Akkhan shoulders", "shoulders", -1980761457),
    ("Akkhan chest", "chest", 259933632),
    ("Akkhan gloves", "hands", 2059399737),
    ("Akkhan pants", "legs", 827015887),
    ("Akkhan boots", "feet", -800755056),
    ("The Witching Hour", "belt", 1771035933),
    ("Strongarm Bracers", "wrists", 923327011),
    ("Darklight", "main", -1791015660),
    ("Stormshield", "offhand", -519190663),
    ("Ring of Royal Grandeur", "ring1", -1149593563),
    ("Convention of Elements", "ring2", 417069418),
    ("Countess Julia's Cameo", "neck", 1566368217),
]
ARMOR_AFFIXES = [1901866878, -620982138, 82091320, -1502864187]
JEWELRY_AFFIXES = [1901866878, -620982138, 966857717, -1502864187]
WEAPON_AFFIXES = [1901866878, -620982138, 966857717, -1502864187]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import Hero_pb2
    import D3Edit
    import Items_pb2

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True, help="installed save user directory")
    ap.add_argument("--output", type=Path, required=True, help="new full save copy to create")
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    if not (source / "account.dat").is_file() or not (source / "heroes").is_dir():
        raise SystemExit("source is not a save user directory")
    provenance = json.loads(PROVENANCE.read_text("utf-8"))
    if (D3EDIT / "Research/extract_cpk.py").exists() is False:
        raise SystemExit("verified D3Edit source missing")
    for rel, want in provenance["file_sha256"].items():
        path = D3EDIT / rel
        if sha(path) != want:
            raise SystemExit("D3Edit source checksum mismatch: " + rel)
    hero_paths = sorted((source / "heroes").glob("*.dat"))
    if len(hero_paths) != 1:
        raise SystemExit(f"expected one hero, found {len(hero_paths)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, output)
    staged_hero = output / "heroes" / hero_paths[0].name
    raw = staged_hero.read_bytes()
    plain = D3Edit.decrypt_save(raw)
    hero = Hero_pb2.SavedDefinition()
    parsed = hero.ParseFromString(plain)
    if parsed != len(plain) or not hero.IsInitialized():
        raise SystemExit("hero protobuf did not parse completely")
    if hero.SerializeToString() != plain or D3Edit.encrypt_save(plain) != raw:
        raise SystemExit("source save round trip is not byte exact")

    templates = {}
    for item in hero.items.items:
        if item.item_slot in GEAR_SLOTS and item.generator.gb_handle.gbid:
            templates.setdefault(item.item_slot, item)
    # Generic schemas are enough because every generated item uses the same
    # SavedItem/Generator layout; select the closest existing template.
    def template_for(slot: int):
        if slot in templates:
            return templates[slot]
        if slot == SLOTS["main"] and SLOTS["main"] in templates:
            return templates[SLOTS["main"]]
        if slot == SLOTS["offhand"] and SLOTS["offhand"] in templates:
            return templates[SLOTS["offhand"]]
        if slot in {SLOTS["ring1"], SLOTS["ring2"], SLOTS["neck"]} and SLOTS["ring2"] in templates:
            return templates[SLOTS["ring2"]]
        if SLOTS["chest"] in templates:
            return templates[SLOTS["chest"]]
        if SLOTS["hands"] in templates:
            return templates[SLOTS["hands"]]
        raise RuntimeError(f"no template for slot {slot}")

    occupied_bag = {i.square_index for i in hero.items.items if i.item_slot == INVENTORY}
    free = [n for n in range(60) if n not in occupied_bag]
    old_equipped = [i for i in hero.items.items if i.item_slot in GEAR_SLOTS]
    moved = []
    for item in old_equipped:
        if not free:
            raise SystemExit("not enough inventory squares to preserve old equipped items")
        square = free.pop(0)
        moved.append({"id": f"{item.id.id_high}:{item.id.id_low}", "from_slot": item.item_slot,
                      "gbid": item.generator.gb_handle.gbid, "to_square": square})
        item.item_slot = INVENTORY
        item.square_index = square

    by_gbid = json.loads(GBIDS.read_text("utf-8"))
    generated = []
    next_id = 0x50000000
    for index, (label, slot_name, gbid) in enumerate(LOADOUT):
        slot = SLOTS[slot_name]
        item = Items_pb2.SavedItem()
        item.CopyFrom(template_for(slot))
        item.id.id_high = 1
        item.id.id_low = next_id + index
        item.hireling_class = 0
        item.item_slot = slot
        item.square_index = 0
        item.used_socket_count = 0
        gen = item.generator
        gen.seed = 0x6A000000 + index
        gen.gb_handle.game_balance_type = 2
        gen.gb_handle.gbid = gbid
        gen.ClearField("rare_item_name")
        gen.ClearField("deprecated_enchant_range_val")
        gen.flags = 43273
        gen.durability = 1000
        gen.max_durability = 1000
        gen.max_durability_original = 1000
        gen.stack_size = 0
        gen.item_quality_level = 9
        gen.item_binding_level = 2
        gen.legendary_item_level = 70
        gen.console_max_level = 70
        gen.transmog_gbid = -1
        gen.enchanted_affix_old = -1
        gen.enchanted_affix_new = -1
        gen.enchanted_affix_count = 0
        del gen.base_affixes[:]
        if slot_name in {"main", "offhand"}:
            gen.base_affixes.extend(WEAPON_AFFIXES)
        elif slot in {SLOTS["ring1"], SLOTS["ring2"], SLOTS["neck"]}:
            gen.base_affixes.extend(JEWELRY_AFFIXES)
        else:
            gen.base_affixes.extend(ARMOR_AFFIXES)
        hero.items.items.add().CopyFrom(item)
        generated.append({"name": label, "slot": slot_name, "slot_id": slot, "gbid": gbid,
                          "asset_name": by_gbid.get(str(gbid), {}).get("name"),
                          "category": by_gbid.get(str(gbid), {}).get("category"),
                          "item_level": 70, "quality_level": 9,
                          "base_affixes": list(gen.base_affixes)})

    for attr in hero.saved_attributes.attributes:
        if attr.key == -4016:
            attr.value = 70
            break
    else:
        raise SystemExit("hero level attribute -4016 not found")
    hero.digest.level = 70
    if not hero.IsInitialized():
        raise SystemExit("generated hero is not initialized")
    out_plain = hero.SerializeToString()
    out_raw = D3Edit.encrypt_save(out_plain)
    if D3Edit.decrypt_save(out_raw) != out_plain:
        raise SystemExit("generated save encryption round trip failed")
    check = Hero_pb2.SavedDefinition(); count = check.ParseFromString(out_plain)
    if count != len(out_plain) or not check.IsInitialized() or check.digest.level != 70:
        raise SystemExit("generated hero did not reload")
    staged_hero.write_bytes(out_raw)
    manifest = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
    report = {
        "source": str(source), "output": str(output),
        "hero_source_sha256": sha(hero_paths[0]),
        "hero_output_sha256": sha(staged_hero),
        "hero_plain_xor_roundtrip": True, "hero_level": hero.digest.level,
        "generated": generated, "moved_existing_equipment": moved,
        "final_item_count": len(hero.items.items), "files": manifest,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"output": str(output), "level": hero.digest.level,
                      "generated": len(generated), "moved": len(moved),
                      "items": len(hero.items.items), "hero_sha256": sha(staged_hero)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
