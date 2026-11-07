"""Verify a multi-item vendor repair on the 0054 build.

Eight items were lowered to roughly a quarter durability with local tooling.  The
repair page quotes per-item fees and 修复装备物品 0 (no equipped item was damaged);
pressing A eight times clears every fee for 622 gold in total and the save ends
with no damaged item.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/vendor-repair-multi-0054"
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
    one = load("repair-one-ui.json")
    done = load("repair-done-ui.json")
    save = load("save-after.json")
    damage = load("damage-steps.json")
    for tag, doc in (("before", before), ("one", one), ("done", done)):
        check("multi-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("multi-damage-steps", len(damage["damaged"]) == 8)
    before_texts = texts(before)
    check("multi-before-fees", "修复装备物品\n费用{c:ffffffff}0 {icon:gold}{/c}" in before_texts and
          any(t.startswith("修复费用{c:ffffffff}") for t in before_texts), before_texts[:4])
    check("multi-one-repair", "-95 {icon:gold}" in texts(one) and "719860 {icon:gold}" in texts(one))
    done_texts = texts(done)
    check("multi-done-zero", "修复所有物品\n费用{c:ffffffff}0 {icon:gold}{/c}" in done_texts)
    check("multi-done-gold", "719333 {icon:gold}" in done_texts)
    part = save["partitions"][0]
    check("multi-save-gold", part["currencies"]["0"] == 719333)
    damaged_left = [i for i in save["heroes"][0]["items"] if i["max_durability"] > 0 and i["durability"] < i["max_durability"]]
    check("multi-save-durability", damaged_left == [])

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 9, "evidence_sha256": evidence,
               "note": "719955 -> 719333 (-622) repairs eight items; 修复装备物品 stays 0 because no equipped item was damaged"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("9 multi-item repair checks passed")


if __name__ == "__main__":
    main()
