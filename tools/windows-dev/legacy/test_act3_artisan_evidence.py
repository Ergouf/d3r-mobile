"""Verify the Act 3 artisan menus on the 0054 build.

Bastion's Keep opens the blacksmith with the five page tabs and the jeweler with
the four gem tabs, matching the Act 1 and Act 5 layout.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act3-town-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def tabs(d):
    return [(x["rect"][0], (x.get("text") or "").strip()) for x in d["items"]
            if x["visible"] and x["rect"][1] == 39 and x["rect"][2] == 156 and (x.get("text") or "").strip()]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    smith = load("smith-menu-ui.json")
    jeweler = load("jeweler-menu-ui.json")
    for tag, doc in (("smith", smith), ("jeweler", jeweler)):
        check("act3-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    smith_tabs = dict(tabs(smith))
    check("act3-smith-five-tabs", sorted(smith_tabs.values()) == sorted(["武器", "护甲", "分解", "修复", "训练"]),
          sorted(smith_tabs.values()))
    check("act3-smith-salvage-page", "要分解的物品" in texts(smith))
    jew_tabs = dict(tabs(jeweler))
    check("act3-jeweler-four-tabs", sorted(jew_tabs.values()) == sorted(["合成", "镶孔", "移除", "训练"]),
          sorted(jew_tabs.values()))
    check("act3-jeweler-name", "沈老贪" in " ".join(texts(jeweler)))
    check("act3-jeweler-combine-page", "合成宝石" in texts(jeweler))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 7, "evidence_sha256": evidence,
               "note": "Act 3 blacksmith shows 武器/护甲/分解/修复/训练 and the jeweler 合成/镶孔/移除/训练"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("7 Act 3 artisan checks passed")


if __name__ == "__main__":
    main()
