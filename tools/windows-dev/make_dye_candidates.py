"""Build dye-item candidate hero saves (local only, never installed here).

Clones an existing stackable gem item (a consumable the game itself accepted)
and swaps only the GBID to Golden Dye, so the structure stays as close to a
game-generated item as we can get.  Three variants differ in item quality only,
because the exact quality of a dye is not documented.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D3EDIT = ROOT / "local/tools/d3edit-clean"
LIVE = Path(r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000_data\save\user.0123456789abcdeffedcba9876543210")
OUT = ROOT / "local/saves/dye-candidates-20261105"
GEM_GBID = 1019190636
DYE_GBID = -234196792  # Golden Dye
HERO_REL = Path("heroes/9af81ba794cf5b64.dat")
FREE_SQUARE = 3


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if not LIVE.is_dir():
        raise SystemExit("live save folder missing")
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import Hero_pb2
    import D3Edit

    raw = (LIVE / HERO_REL).read_bytes()
    plain = D3Edit.decrypt_save(raw)
    base = Hero_pb2.SavedDefinition()
    if base.ParseFromString(plain) != len(plain) or not base.IsInitialized():
        raise SystemExit("hero protobuf is not complete")
    if D3Edit.encrypt_save(plain) != raw or base.SerializeToString() != plain:
        raise SystemExit("no-op roundtrip is not byte exact")

    gem = next(it for it in base.items.items
               if it.generator.gb_handle.gbid == GEM_GBID and it.item_slot == 272)
    print("gem source:", gem.square_index, gem.generator.flags, gem.generator.item_quality_level)

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"source": str(LIVE), "hero": str(HERO_REL), "gem_gbid": GEM_GBID,
                "dye_gbid": DYE_GBID, "square": FREE_SQUARE, "variants": {}}
    for tag, quality in (("A_gem_like", 4), ("B_common", 0), ("C_magic", 1)):
        hero = Hero_pb2.SavedDefinition()
        hero.CopyFrom(base)
        clone = hero.items.items.add()
        clone.CopyFrom(gem)
        clone.square_index = FREE_SQUARE
        clone.generator.gb_handle.gbid = DYE_GBID
        clone.generator.item_quality_level = quality
        encoded = hero.SerializeToString()
        check = Hero_pb2.SavedDefinition()
        if check.ParseFromString(encoded) != len(encoded) or not check.IsInitialized():
            raise SystemExit("variant does not decode: " + tag)
        item = next(i for i in check.items.items if i.square_index == FREE_SQUARE and i.item_slot == 272)
        if item.generator.gb_handle.gbid != DYE_GBID or item.generator.stack_size != gem.generator.stack_size:
            raise SystemExit("variant mismatch: " + tag)
        folder = OUT / tag
        folder.mkdir(exist_ok=True)
        (folder / HERO_REL.parent).mkdir(parents=True, exist_ok=True)
        (folder / HERO_REL).write_bytes(D3Edit.encrypt_save(encoded))
        manifest["variants"][tag] = {"quality": quality, "hero_sha256": sha(folder / HERO_REL),
                                     "items_before": len(base.items.items),
                                     "items_after": len(check.items.items)}
        print(tag, "items", len(check.items.items), "sha", sha(folder / HERO_REL)[:16])
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    print("candidates at", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
