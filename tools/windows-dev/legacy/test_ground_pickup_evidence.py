"""Verify drop then ground pickup on the 0054 build.

Discarding the selected bag item (pad Y) takes the bag from 18/60 to 17/60 and
creates a ground entity (SNO 145928) at the player's feet; a mouse click on it
operates the item, the entity disappears and the bag returns to 18/60.  The save
keeps 23 hero items and 719203 gold.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/pickup-drop-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"
ITEM_SNO = 145928


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    before = load("bag-before-ui.json")
    selected = load("item-selected-ui.json")
    dropped = load("bag-after-drop-ui.json")
    picked = load("bag-after-pickup-ui.json")
    ground_before = load("ground-before-pickup.json")
    ground_after = load("ground-after-pickup.json")
    save = load("save-after.json")

    for tag, doc in (("before", before), ("dropped", dropped), ("picked", picked)):
        check("pickup-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("pickup-bag-before", "物品栏 {c_white}18/60{/c}" in texts(before) and
          any("恐惧柳叶刀" in t for t in texts(before)))
    check("pickup-drop-legend", any(t.startswith("{icon:button") and "丢弃" in t for t in texts(selected)))
    check("pickup-bag-after-drop", "物品栏 {c_white}17/60{/c}" in texts(dropped) and
          not any("恐惧柳叶刀" in t for t in texts(dropped)))
    ent_before = [e for e in ground_before["result"]["entities"] if e["sno"] == ITEM_SNO]
    ent_after = [e for e in ground_after["result"]["entities"] if e["sno"] == ITEM_SNO]
    check("pickup-ground-entity", len(ent_before) == 1 and abs(ent_before[0]["distance"]) < 2.0)
    check("pickup-entity-gone", ent_after == [])
    check("pickup-bag-restored", "物品栏 {c_white}18/60{/c}" in texts(picked) and
          any("恐惧柳叶刀" in t for t in texts(picked)))
    part = save["partitions"][0]
    check("pickup-save", len(save["heroes"][0]["items"]) == 23 and part["currencies"]["0"] == 719203)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 10, "evidence_sha256": evidence,
               "note": "drop 18/60 -> 17/60 with ground SNO 145928, mouse click picks it up -> 18/60 and 23 saved items"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("10 drop/pickup checks passed")


if __name__ == "__main__":
    main()
