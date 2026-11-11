"""Verify 修复所有物品 (pad Y) on the 0054 build.

With the skill keys back on the documented defaults (x=C, y=V) the probe can send
the Y action: one press clears both damaged items, 719247 -> 719204 (-43), and the
save ends with no damaged item.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/vendor-repair-all-0054"
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
    after = load("repair-after-y-ui.json")
    save = load("save-after.json")
    for tag, doc in (("before", before), ("after", after)):
        check("repair-all-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    before_texts = texts(before)
    check("repair-all-before", "修复费用{c:ffffffff}10 {icon:gold}{/c}" in before_texts and
          "719247 {icon:gold}" in before_texts)
    after_texts = texts(after)
    check("repair-all-charged", "-43 {icon:gold}" in after_texts and "719204 {icon:gold}" in after_texts)
    check("repair-all-zero", "修复所有物品\n费用{c:ffffffff}0 {icon:gold}{/c}" in after_texts)
    part = save["partitions"][0]
    check("repair-all-save-gold", part["currencies"]["0"] == 719204)
    damaged_left = [i for i in save["heroes"][0]["items"] if i["max_durability"] > 0 and i["durability"] < i["max_durability"]]
    check("repair-all-save-durability", damaged_left == [])
    keybinds = (EVID / "keybinds.ini").read_text("ascii", errors="replace")
    check("repair-all-default-keys", "x=C" in keybinds and "y=V" in keybinds)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 8, "evidence_sha256": evidence,
               "note": "one Y (C key) press repairs both items: 719247 -> 719204 (-43), no damaged item left"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("8 repair-all checks passed")


if __name__ == "__main__":
    main()
