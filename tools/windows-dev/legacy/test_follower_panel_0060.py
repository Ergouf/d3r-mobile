"""Record the 0060 follower panel result in Act 1 town.

Clicking the Scoundrel (SNO 4644) opens a panel whose only decoded content is
the name 痞子 and a {icon:button4} close button; no 技能/装备/招募 text is
present, reproducing the offline-save limitation.
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

    click = load("click-templar-4538.json")
    check("native-follower-click", click["down"] == 1 and click["up"] == 1 and
          click["build"]["exe_sha256"] == BUILD)
    panel = load("templar-panel.json")
    panel_text = "\n".join(texts(panel))
    check("follower-panel-close-icon", "{icon:button4}" in panel_text)
    check("follower-panel-name", "痞子" in panel_text)
    check("no-skill-body", "技能" not in panel_text)
    check("no-equipment-body", "装备" not in panel_text)
    check("no-recruit-body", "招募" not in panel_text)
    (EVID / "follower-panel-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
        "panel": "name + button4 only",
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} follower panel checks passed")


if __name__ == "__main__":
    main()
