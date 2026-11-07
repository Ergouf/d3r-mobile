"""Verify 修复装备物品 (pad X) on the 0054 build.

Only the equipped main hand was lowered to 139/557, so the page quotes 1 gold for
修复装备物品 and 1 for 修复所有物品; the X action repairs just the equipped item,
leaving 719203 gold and 557/557 durability in the save.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/vendor-repair-equipped-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    before = load("repair-before-ui.json")
    after = load("repair-after-x-ui.json")
    save = load("save-after.json")
    damage = load("damage-step.json")
    for tag, doc in (("before", before), ("after", after)):
        check("equip-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("equip-damage-step", damage["durability"]["after"] == 139 and damage["slot"] == 336)
    before_texts = texts(before)
    check("equip-before-fee", "修复装备物品\n费用{c:ffffffff}1 {icon:gold}{/c}" in before_texts and
          "719204 {icon:gold}" in before_texts, before_texts[:4])
    after_texts = texts(after)
    check("equip-after-fee", "修复装备物品\n费用{c:ffffffff}0 {icon:gold}{/c}" in after_texts)
    check("equip-charged", "-1 {icon:gold}" in after_texts and "719203 {icon:gold}" in after_texts)
    item = [i for i in save["heroes"][0]["items"] if i["slot"] == 336][0]
    check("equip-save-durability", item["durability"] == 557 and item["max_durability"] == 557)
    check("equip-save-gold", save["partitions"][0]["currencies"]["0"] == 719203)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 8, "evidence_sha256": evidence,
               "note": "X repairs only the equipped item: 139/557 -> 557/557 for 1 gold"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("8 equipped-repair checks passed")


if __name__ == "__main__":
    main()
