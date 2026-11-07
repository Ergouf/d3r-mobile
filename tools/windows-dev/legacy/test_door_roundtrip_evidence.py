"""Verify the inn door round trip on the 0054 build.

Clicking the inn door (SNO 178293) walked the player through into the interior
(place 1999568897); clicking the exit door inside walked back out to the town
(place 1999503360).
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/door-roundtrip-0054"
TOWN = 1999503360
INN = 1999568897


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    inside = load("inside-scan.json")["result"]
    outside = load("outside-scan.json")["result"]
    check("door-inside-place", inside["place"] == INN, inside["place"])
    check("door-outside-place", outside["place"] == TOWN, outside["place"])
    check("door-inside-position", round(inside["pos"][0]) != round(outside["pos"][0]))
    check("door-inside-not-town", inside["place"] != outside["place"])

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "checks": 6, "evidence_sha256": evidence,
               "note": "inn door walk-in lands at place 1999568897 and the exit door returns to 1999503360"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("4 door round-trip checks passed")


if __name__ == "__main__":
    main()
