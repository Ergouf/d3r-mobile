"""Verify Act 4 blacksmith exposes all five functional pages."""

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act4-artisan-0059"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(name):
    return [(i.get("text") or "") for i in load(name)["items"] if i.get("visible") and i.get("text")]


def main():
    checks = []
    def check(name, cond):
        assert cond, name
        checks.append(name)
        print("PASS " + name)

    tabs = {"武器", "护甲", "分解", "修复", "训练"}
    page_markers = {
        "武器": "专家战争剑",
        "护甲": "学徒锁子甲",
        "分解": "要分解的物品",
        "修复": "修复所有物品",
        "训练": "将最高物品锻造等级提升到35",
    }
    for page, marker in page_markers.items():
        body = texts("act4-smith-page-" + page + ".json")
        check("page-" + page, tabs.issubset(set(body)) and any(marker in t for t in body))
    train = texts("act4-smith-page-训练.json")
    check("training-cost", any("15000 {icon:gold}" in t for t in train))
    check("training-next-level", any("将最高物品锻造等级提升到35" in t for t in train) and "4" in train)
    check("same-build", all(load(n)["build"]["exe_sha256"] ==
          "B18FEFD0A9745FFB62992C646FC8454B4E7F58F42A670D4AC6340BBF06E1C6BE"
          for n in ["act4-smith-click3.json"] + [f"act4-smith-page-{p}.json" for p in tabs]))
    (EVID / "act4-artisan-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "tabs": sorted(tabs),
        "result": "Act 4 blacksmith exposes weapon/armor/salvage/repair/training; training page next level 5 costs 15000 and lists level-35 recipes"
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} Act-4 artisan checks passed")

if __name__ == "__main__":
    main()
