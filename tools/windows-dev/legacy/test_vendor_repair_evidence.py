"""Verify the enabled-state vendor repair on the 0054 build.

One item was lowered to 129/517 durability with local tooling; the vendor's 修复
page then quotes 33 gold, the footer 修复 legend pays it, and the save shows the
item back at 517/517.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/vendor-repair-0054"
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
    page = load("repair-page-ui.json")
    done = load("repair-done-ui.json")
    save = load("save-after.json")
    damage = load("damage-step.json")
    for tag, doc in (("page", page), ("done", done)):
        check("repair-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("repair-damage-step", damage["durability"]["after"] == 129 and damage["durability"]["max"] == 517)
    joined = " ".join(texts(page))
    check("repair-quote", "修复费用{c:ffffffff}33 {icon:gold}{/c}" in joined, joined[:100])
    check("repair-legend", any("修复所有物品" in t for t in texts(page)))
    done_texts = " ".join(texts(done))
    check("repair-charged", "-33 {icon:gold}" in done_texts and "729955 {icon:gold}" in done_texts)
    check("repair-no-fee-left", "修复所有物品\n费用{c:ffffffff}0 {icon:gold}{/c}" in texts(done))
    item = [i for i in save["heroes"][0]["items"] if i["gbid"] == damage["item_gbid"]][0]
    check("repair-save-durability", item["durability"] == 517 and item["max_durability"] == 517)
    check("repair-save-gold", save["partitions"][0]["currencies"]["0"] == 729955)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 9, "evidence_sha256": evidence,
               "note": "129/517 -> repaired for 33 gold, save shows 517/517 and 729955 gold"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("9 vendor repair checks passed")


if __name__ == "__main__":
    main()
