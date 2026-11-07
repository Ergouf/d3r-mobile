"""Verify leaving the dungeon back to town on the 0054 build.

The character travelled into the cathedral (place 1999765508), then quit to the
main menu and pressed 继续; the new session spawns back in town (place
1999503360).  Returning through the waypoint map was not used here because the
selection cursor could not be moved onto the town node.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/dungeon-roundtrip-0054"
CATHEDRAL = 1999765508
TOWN = 1999503360


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    dungeon = load("dungeon-scan.json")["result"]
    town = load("town-after-restart.json")["result"]
    m = load("dungeon-map-ui.json")
    check("roundtrip-in-dungeon", dungeon["place"] == CATHEDRAL, dungeon["place"])
    check("roundtrip-back-town", town["place"] == TOWN, town["place"])
    check("roundtrip-place-changed", dungeon["place"] != town["place"])
    check("roundtrip-town-position", abs(town["pos"][0] - 391.2) < 5 and abs(town["pos"][1] - 581.2) < 5, town["pos"])
    check("roundtrip-waypoint-label", any("大教堂一层" in (x.get("text") or "").replace("\n", " / ") and
                                          "传送点" in (x.get("text") or "") for x in m["items"] if x["visible"]))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "checks": 5, "evidence_sha256": evidence,
               "note": "cathedral 1999765508 -> quit to menu -> 继续 -> town 1999503360"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("5 dungeon round-trip checks passed")


if __name__ == "__main__":
    main()
