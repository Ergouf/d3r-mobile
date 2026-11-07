"""Re-verify Act 5 town menus on build 0060.

After the game-settings chapter switch the main menu reads 冒险模式 - 普通
第五幕; the loaded town exposes the Westmarch layout (waypoint SNO 6442,
blacksmith 56947) and the blacksmith menu shows all five tabs.  The 训练 tab
page shows the next tier requirements (需要等级 35, 所需材料).
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

    menu = load("r2-after-act5.json")
    menu_text = "\n".join(texts(menu))
    check("act5-main-menu", "第五幕" in menu_text and "冒险模式" in menu_text)
    scan = load("act1-scan.json")
    rows = scan["rows"]
    waypoint = [r for r in rows if r["sno"] == 6442]
    check("westmarch-waypoint", bool(waypoint) and waypoint[0]["type"] == 2)
    smith = [r for r in rows if r["sno"] == 56947]
    check("act5-blacksmith-entity", bool(smith) and smith[0]["type"] == 1)
    ui = load("blacksmith-ui.json")
    ui_text = "\n".join(texts(ui))
    check("blacksmith-name", "黑德里格·埃蒙" in ui_text)
    check("five-tabs", all(t in ui_text for t in ("武器", "护甲", "分解", "修复", "训练")))
    train = load("train-page.json")
    train_text = "\n".join(texts(train))
    check("train-page-header", any(t.strip() == "训练" for t in texts(train)))
    check("train-requirement", "需要等级" in train_text and "35" in train_text)
    check("train-materials", "所需材料" in train_text)
    click = load("click-train-tab.json")
    check("native-tab-click", click["down"] == 1 and click["up"] == 1 and
          click["build"]["exe_sha256"] == BUILD)
    jewel = load("jeweler-ui.json")
    jewel_text = "\n".join(texts(jewel))
    check("jeweler-name", "沈老贪" in jewel_text)
    check("jeweler-four-tabs", all(t in jewel_text for t in ("合成", "镶孔", "移除", "训练")))
    jclick = load("click-jeweler-56949.json")
    check("native-jeweler-click", jclick["down"] == 1 and jclick["up"] == 1 and
          jclick["build"]["exe_sha256"] == BUILD)
    jtrain = load("jeweler-train.json")
    jtrain_text = "\n".join(texts(jtrain))
    check("jeweler-train-page", any(t.strip() == "训练" for t in texts(jtrain)))
    check("jeweler-train-level5", "等级{c_white}5{/c}" in jtrain_text)
    check("jeweler-train-materials", "所需材料" in jtrain_text)
    myst = load("mystic-ui4.json")
    myst_text = "\n".join(texts(myst))
    check("mystic-name", "米丽安" in myst_text)
    check("mystic-four-tabs", all(t in myst_text for t in ("附魔", "幻化", "染色", "训练")))
    mclick = load("click-mystic3.json")
    check("native-mystic-click", mclick["down"] == 1 and mclick["up"] == 1 and
          mclick["build"]["exe_sha256"] == BUILD)
    mtrain = load("mystic-train.json")
    mtrain_text = "\n".join(texts(mtrain))
    check("mystic-train-page", "训练秘士来学会新的配方" in mtrain_text)
    check("mystic-train-materials", "所需材料" in mtrain_text)
    (EVID / "act5-menus-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
        "waypoint_sno": 6442, "blacksmith_sno": 56947,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} act5 menu checks passed")


if __name__ == "__main__":
    main()
