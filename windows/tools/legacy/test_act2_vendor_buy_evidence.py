"""Verify a purchase at the Act 2 vendor (Squirt, SNO 180783).

The buy page lists a 121040-gold item; a mouse select plus the 购买 legend takes
the gold to 729988 and the bag from 17/60 to 18/60, and the save agrees.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act2-vendor-buy-0054"
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
    page = load("vendor-buy-ui.json")
    selected = load("vendor-buy-selected-ui.json")
    done = load("vendor-buy-done-ui.json")
    save = load("save-after.json")
    for tag, doc in (("page", page), ("selected", selected), ("done", done)):
        check("buy2-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    joined = " ".join(texts(page))
    check("vendor-buy-price", "121040 {icon:gold}" in joined and "物品栏 {c_white}17/60{/c}" in joined)
    check("vendor-buy-legend", any(t.startswith("{icon:button1") and "购买" in t for t in texts(selected)))
    done_texts = " ".join(texts(done))
    check("vendor-buy-charged", "-121040 {icon:gold}" in done_texts and "物品栏 {c_white}18/60{/c}" in done_texts)
    part = save["partitions"][0]
    check("vendor-buy-save", part["currencies"]["0"] == 729988 and part["currencies"]["1"] == 425)
    check("vendor-buy-item", len(save["heroes"][0]["items"]) == 23)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 7, "evidence_sha256": evidence,
               "note": "121040 gold spent, bag 17/60 -> 18/60, save gold 729988 and 23 hero items"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("7 Act 2 vendor purchase checks passed")


if __name__ == "__main__":
    main()
