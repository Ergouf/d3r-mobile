"""Verify the Act 4 jeweler menu on build 0060.

The fresh process is switched to 第四幕 from the settings chapter tab, the
town scan exposes jeweler SNO 56949, and a native mouse click followed by the
A action opens the jeweler with 合成/镶孔/移除/训练.  The training tab shows
the 等级 5 recipes and 所需材料.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act5-r6"
BUILD = "4F4C0D7265C5E2354B197ECF95B93F3B56D9A19F6DD36145387CF87047B43F13"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(doc):
    return [(i.get("text") or "") for i in doc["items"] if i.get("visible") and i.get("text")]


def main():
    checks = []
    def check(name, cond):
        assert cond, name
        checks.append(name)
        print("PASS " + name)

    menu = load("menu-act4-r2.json")
    menu_text = "\n".join(texts(menu))
    check("act4-main-menu", "第四幕" in menu_text and "冒险模式" in menu_text)
    scan = load("act4-scan.json")
    jewel = [r for r in scan["rows"] if r["sno"] == 56949]
    check("act4-jeweler-entity", bool(jewel) and jewel[0]["type"] == 1)
    click = load("act4-click-jeweler.json")
    check("native-jeweler-click", click["down"] == 1 and click["up"] == 1 and
          click["build"]["exe_sha256"] == BUILD)
    ui = load("act4-jeweler-ui.json")
    ui_text = "\n".join(texts(ui))
    check("jeweler-tabs", all(t in ui_text for t in ("合成", "镶孔", "移除", "训练")))
    train = load("act4-jeweler-train.json")
    train_text = "\n".join(texts(train))
    check("jeweler-train-level5", "等级{c_white}5{/c}" in train_text)
    check("jeweler-train-body", "训练珠宝匠来学会新的配方" in train_text)
    check("jeweler-train-materials", "所需材料" in train_text)
    (EVID / "act4-jeweler-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD, "jeweler_sno": 56949,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} act4 jeweler checks passed")


if __name__ == "__main__":
    main()
