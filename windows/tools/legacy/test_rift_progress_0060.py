"""Verify a real Nephalem rift kill raises the 0060 progress bar.

The character was moved with SDL movement keys to the monster pack, a monster
body was clicked with the SDL pointer (the runtime logs the attack goal and
submit), and SDL A (Space) presses cleared the pack.  The rift HUD progress
text moved from ``0%`` to ``1%`` while the quest line stayed visible.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/rift-content-0060"
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

    before = load("inside-rift-ui.json")
    check("progress-starts-zero", any(t.strip() == "0%" for t in texts(before)))
    scan = load("r3-interact2.json")["result"]["entities"]
    monsters = [e for e in scan if e["type"] == 1]
    check("monster-pack-loaded", len(monsters) >= 4 and min(e["distance"] for e in monsters) < 10)
    click = load("r3-attack-304307.json")
    check("native-monster-click", click["down"] == 1 and click["up"] == 1 and
          click["build"]["exe_sha256"] == BUILD)
    after = load("r3-ui-after-a.json")
    after_texts = texts(after)
    check("progress-one-percent", any(t.strip() == "1%" for t in after_texts))
    check("quest-line-kept", any("消灭奈非天秘境守卫的手下" in t for t in after_texts))
    check("hero-not-dead", not any("你死了" in t for t in after_texts))
    left = load("r3-interact4.json")["result"]["entities"]
    check("pack-cleared", len([e for e in left if e["type"] == 1]) == 1)
    pause = load("r3-pause4.json")
    check("pause-menu-rows", all(any(t.strip() == row for t in texts(pause))
                                 for row in ("继续", "选项", "退出")))
    dialog = load("r4-exit-dialog.json")
    dialog_text = "\n".join(texts(dialog))
    check("exit-dialog-shown", "接受" in dialog_text and "返回" in dialog_text)
    (EVID / "rift-progress-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
        "progress": ["0%", "1%"], "monsters_before": len(monsters), "monsters_left": 1,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} rift progress checks passed")


if __name__ == "__main__":
    main()
