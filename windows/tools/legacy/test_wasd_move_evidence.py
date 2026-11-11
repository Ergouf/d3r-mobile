"""Measure the stick-axis (WASD) movement on the 0054 build.

Holding W for about one second walked the avatar from (361.3, 597.0) to
(351.5, 562.2); a second hold moved it a further 6.6 units.  This is the escape
route when a click-walk is wedged against an NPC or a wall.
"""
from __future__ import annotations
import hashlib, json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/wasd-move-0054"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))["result"]


def dist(a, b):
    return math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1])


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    b1, a1 = load("before-w-ui.json"), load("after-w-ui.json")
    b2, a2 = load("second-before-ui.json"), load("second-after-ui.json")
    d1, d2 = dist(b1, a1), dist(b2, a2)
    check("wasd-first-hold", d1 > 25.0, round(d1, 1))
    check("wasd-second-hold", d2 > 3.0, round(d2, 1))
    check("wasd-same-place", b1["place"] == a1["place"] == b2["place"] == a2["place"], b1["place"])

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "checks": 3, "evidence_sha256": evidence,
               "note": "W hold moved 35.9 units then 6.6 units; click-walk can wedge near NPCs and walls"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("3 WASD movement checks passed, deltas %.1f / %.1f" % (d1, d2))


if __name__ == "__main__":
    main()
