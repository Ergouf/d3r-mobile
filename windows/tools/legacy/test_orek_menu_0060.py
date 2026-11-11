"""Verify Orek's 关于欧雷克 / 取消 options on build 0060.

A native mouse click on Orek opens 唤醒/秘境/关于欧雷克/取消; clicking
关于欧雷克 leaves a panel titled 欧雷克, and clicking 取消 removes every menu
row from the visible UI.
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

    click = load("r8-click-orek.json")
    check("native-orek-click", click["down"] == 1 and click["up"] == 1 and
          click["build"]["exe_sha256"] == BUILD)
    menu = load("r8-orek-menu.json")
    menu_text = "\n".join(texts(menu))
    check("orek-menu-rows", all(t in menu_text for t in ("唤醒", "秘境", "关于欧雷克", "取消")))
    about = load("r8-click-about.json")
    check("about-click", about["enginePixel"] == [539, 239] and about["build"]["exe_sha256"] == BUILD)
    panel = load("r8-orek-about.json")
    check("about-panel-title", any(t.strip() == "欧雷克" for t in texts(panel)))
    cancel = load("r8-click-cancel.json")
    check("cancel-click", cancel["enginePixel"] == [539, 269] and cancel["build"]["exe_sha256"] == BUILD)
    after = load("r8-after-cancel.json")
    after_text = "\n".join(texts(after))
    check("cancel-closes-menu", "取消" not in after_text and "关于欧雷克" not in after_text)
    (EVID / "orek-menu-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} orek checks passed")


if __name__ == "__main__":
    main()
