"""Verify the generated level-70 Akkhan loadout and its in-game rendering."""

from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOADOUT = ROOT / "out/windows/kbm/session/maxgear-0059/loadout"
EXPECTED = {
    288: (-1992164625, "阿克汉的头盔"),
    400: (-1980761457, "阿克汉的肩甲"),
    304: (259933632, "阿克汉的胸甲"),
    352: (2059399737, "阿克汉的护手"),
    416: (827015887, "阿克汉的腿甲"),
    384: (-800755056, "阿克汉的钢靴"),
    368: (1771035933, "行巫时刻"),
    432: (923327011, "力士护腕"),
    336: (-1791015660, "黑暗之光"),
    320: (-519190663, "暴风之盾"),
    464: (-1149593563, "皇家华戒"),
    448: (417069418, "全能法戒"),
    480: (1566368217, "茱莉雅女爵的雕饰项链"),
}
SLOT_UI = {
    "head": "slot-head.json", "shoulders": "slot-shoulder.json", "chest": "slot-torso.json",
    "hands": "slot-hands.json", "legs": "slot-legs.json", "feet": "slot-feet.json",
    "belt": "slot-waist.json", "wrists": "slot-bracers.json",
    "main": "slot-armleft.json", "offhand": "slot-armright.json",
    "ring1": "slot-fingerleft.json", "ring2": "slot-fingerright.json",
    "neck": "slot-neck.json",
}


def load(path):
    return json.loads(path.read_text("utf-8"))


def main():
    checks = []
    used = {}
    def check(name, cond):
        assert cond, name
        checks.append(name)
        print("PASS " + name)

    report = load(LOADOUT / "generation-report.json")
    final = load(ROOT / "out/windows/kbm/session/maxgear-0059/final-snapshot.json")
    generated_snapshot = load(LOADOUT / "generated-snapshot.json")
    old = load(LOADOUT / "source-snapshot.json")
    hero = final["heroes"][0]
    equipped = {i["slot"]: i for i in hero["items"] if i["slot"] != 272}
    generated_equipped = {i["slot"]: i for i in generated_snapshot["heroes"][0]["items"] if i["slot"] != 272}
    check("level-70-hero", report["hero_level"] == hero["level"] == 70 and old["heroes"][0]["level"] == 70)
    check("thirteen-generated", len(report["generated"]) == 13 and len(equipped) == 13)
    check("slot-and-gbid", {k: (v[0], equipped[k]["gbid"]) for k, v in EXPECTED.items()} ==
          {k: (v[0], v[0]) for k, v in EXPECTED.items()})
    check("item-level-70", all(i.get("item_level") == 70 and i.get("quality_level") == 9 for i in report["generated"]))
    check("durability-1000", all(generated_equipped[k]["durability"] == 1000 and generated_equipped[k]["max_durability"] == 1000 for k in EXPECTED))
    check("unique-item-ids", len({i["id"] for i in hero["items"]}) == len(hero["items"]))
    check("old-equipment-preserved", len(report["moved_existing_equipment"]) == 5 and
          len(old["heroes"][0]["items"]) == 23 and report["final_item_count"] == 36)
    check("play-loot-appended", len(hero["items"]) == 39)
    check("account-preserved", old["partitions"][0]["currencies"]["0"] == 717579 and
          final["partitions"][0]["currencies"]["0"] == 718003 and
          final["partitions"][0]["crafter_levels"] == [4, 9, 10, 0])
    loaded = load(ROOT / "out/windows/kbm/session/maxgear-0058/loaded-scene.json")
    hp = [e["attrs"] for e in loaded["result"]["entities"] if e["type"] == 7]
    check("runtime-high-hp", len(hp) == 1 and hp[0]["Hitpoints_Max_Total"] == 1353916)
    ui_names = {
        "head": "阿克汉的头盔", "shoulders": "阿克汉的肩甲", "chest": "阿克汉的胸甲",
        "hands": "阿克汉的护手", "legs": "阿克汉的腿甲", "feet": "阿克汉的钢靴",
        "belt": "行巫时刻", "wrists": "力士护腕", "main": "黑暗之光", "offhand": "暴风之盾",
        "ring1": "皇家华戒", "ring2": "全能法戒", "neck": "茱莉雅女爵的雕饰项链",
    }
    for slot, filename in SLOT_UI.items():
        data = load(LOADOUT / filename)
        check("ui-" + slot, any(ui_names[slot] in (i.get("text") or "") for i in data["items"]))
    for p in LOADOUT.iterdir():
        if p.is_file(): used[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (ROOT / "out/windows/kbm/session/maxgear-0059/loadout-summary.json").write_text(
        json.dumps({"scope": __doc__, "checks": checks, "build": loaded["build"], "evidence_sha256": used,
                    "result": "13 level-70 items accepted by game; max HP 1,353,916"}, ensure_ascii=False, indent=2) + "\n",
        "utf-8")
    print(f"{len(checks)} maxgear checks passed")

if __name__ == "__main__":
    main()
