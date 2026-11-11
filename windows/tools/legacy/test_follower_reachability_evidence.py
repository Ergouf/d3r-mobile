"""Record why the follower panel is unreachable in this profile.

The character sheet exposes 物品栏/技能/巅峰/队伍/任务, but the 队伍 tab is disabled
in the offline session (runtime log: "UI tab disabled current=0 target=3"), so the
click leaves the 物品栏 page in place.  The Scoundrel shows only a world nameplate
with a Y hint, and the synthesized operate on him is rejected at 4.41.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/follower-blocked-0053"
BUILD = "C2BFEDBAEB3C82683C95198E61E382F26D0C85D2A61E682B2C038AF78B9AE12F"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def page_header(d):
    for x in d["items"]:
        if x["visible"] and x["rect"][:2] == [-3, -27] and x["rect"][2] == 258:
            return (x.get("text") or "").strip()
    raise AssertionError("no page header")


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    sheet = load("sheet-tabs-ui.json")
    party = load("party-tab-ui.json")
    name = load("scoundrel-name-ui.json")
    for tag, doc in (("sheet", sheet), ("party", party), ("name", name)):
        check("follower-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    tabs = ("物品栏", "技能", "巅峰", "队伍", "任务")
    check("follower-sheet-tabs", all(t in texts(sheet) for t in tabs))
    joined = " ".join(texts(party))
    check("follower-party-tab-disabled", "狂热刀刺" in joined and "物品栏" in joined)
    check("follower-scoundrel-nameplate", "痞子" in texts(name))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 6, "evidence_sha256": evidence,
               "note": "队伍 tab disabled in the offline session (UI tab disabled current=0 target=3); Scoundrel operate rejected at 4.41"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("6 follower reachability checks passed")


if __name__ == "__main__":
    main()

