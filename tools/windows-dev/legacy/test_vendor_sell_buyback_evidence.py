"""Verify vendor sell and buy-back at Squirt (Act 2) on the 0054 build.

Selling the selected item raises the purse 729988 -> 730497 (+509) and the same
item appears on the 回购 page at 509; buying it back returns the purse to 729988,
so the save shows the original gold and the same 23 hero items.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/vendor-sell-buyback-0054"
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
    selected = load("sell-selected-ui.json")
    sold = load("sell-done-ui.json")
    buyback = load("buyback-list-ui.json")
    bought = load("buyback-done-ui.json")
    save = load("save-after.json")
    for tag, doc in (("selected", selected), ("sold", sold), ("buyback", buyback), ("bought", bought)):
        check("sell-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("sell-legend", any(t.startswith("{icon:button1") and "出售" in t for t in texts(selected)))
    check("sell-price", "出售价格{c:ffffffff}509 {icon:gold}{/c}" in texts(selected))
    check("sell-gold-up", "730497 {icon:gold}" in texts(sold) and "509 {icon:gold}" in texts(sold))
    check("buyback-listed", any("509 {icon:gold}" == t for t in texts(buyback)))
    check("buyback-gold-down", "729988 {icon:gold}" in texts(bought) and "-509 {icon:gold}" in texts(bought))
    part = save["partitions"][0]
    check("sell-save-roundtrip", part["currencies"]["0"] == 729988 and
          len(save["heroes"][0]["items"]) == 23 and part["currencies"]["1"] == 425)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 10, "evidence_sha256": evidence,
               "note": "sell +509 then buy back -509 leaves 729988 gold and 23 items"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("10 vendor sell/buyback checks passed")


if __name__ == "__main__":
    main()
