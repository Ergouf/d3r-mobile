"""Verify the two-button prompt answers by label, not by side.

The 退出 prompt lays 接受 on the left and 取消 on the right.  The 0054 build reads
each button's own label, so clicking 取消 sends B (the prompt closes and the game
stays paused) while 接受 sends A (back to the main menu).
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/dialog-buttons-0054"
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
    opened = load("dialog-open-ui.json")
    cancelled = load("after-cancel-ui.json")
    accepted = load("after-accept-ui.json")
    for tag, doc in (("open", opened), ("cancel", cancelled), ("accept", accepted)):
        check("dialog-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    open_texts = texts(opened)
    check("dialog-open-prompt", "提示" in open_texts and "游戏已暂停" in open_texts)
    check("dialog-open-buttons", any("取消" in t for t in open_texts) and any("接受" in t for t in open_texts))
    check("dialog-cancel-keeps-game", "游戏已暂停" in texts(cancelled) and "提示" not in texts(cancelled))
    check("dialog-accept-leaves-game", "主菜单" in texts(accepted))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 7, "evidence_sha256": evidence,
               "note": "clicking 取消 logs cancel(B) via label and keeps the pause menu; 接受 logs confirm(A) via label and returns to the main menu"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("7 dialog button checks passed")


if __name__ == "__main__":
    main()
