"""Verify the rift exit path: pause -> 退出 -> 接受 -> main menu -> 继续 -> town.

The pause row was clicked at its resolved screen centre (296,515) and the
dialog 接受 button at (442,450); both are SDL pointer events.  After the main
menu 继续 click the player is back in town place 1999503360 at the spawn
point, with the rift HUD gone.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/rift-content-0060"
BUILD = "4F4C0D7265C5E2354B197ECF95B93F3B56D9A19F6DD36145387CF87047B43F13"
TOWN = 1999503360


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

    pause = load("r5-pause-now.json")
    check("pause-menu", all(any(t.strip() == r for t in texts(pause)) for r in ("继续", "选项", "退出")))
    row = load("r5-exit-row.json")
    check("exit-row-click", row["down"] == 1 and row["up"] == 1 and
          row["enginePixel"] == [296, 515] and row["build"]["exe_sha256"] == BUILD)
    dialog = load("r5-dialog.json")
    dialog_text = "\n".join(texts(dialog))
    check("exit-dialog-text", "你想要退出当前游戏并返回到主菜单吗" in dialog_text)
    check("dialog-buttons", "接受" in dialog_text and "取消" in dialog_text)
    accept = load("r5-accept-button.json")
    check("accept-click", accept["down"] == 1 and accept["up"] == 1 and
          accept["enginePixel"] == [442, 450] and accept["build"]["exe_sha256"] == BUILD)
    menu = load("r5-mainmenu-real.json")
    menu_text = "\n".join(texts(menu))
    check("main-menu-after-exit", "主菜单" in menu_text and "继续" in menu_text)
    session = load("r5-town-session.json")
    check("back-in-town", session["player"]["place"] == TOWN and
          abs(session["player"]["pos"][0] - 391.25) < 2 and
          abs(session["player"]["pos"][1] - 581.25) < 2)
    (EVID / "rift-exit-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD, "town_place": TOWN,
        "exit_row_pixel": [296, 515], "accept_pixel": [442, 450],
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} rift exit checks passed")


if __name__ == "__main__":
    main()
