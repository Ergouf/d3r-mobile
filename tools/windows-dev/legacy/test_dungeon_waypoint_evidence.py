"""Verify the waypoint inside a dungeon on the 0054 build.

From the first cathedral instance (place 1999699971) the waypoint map selected the
next destination and A travelled to a different place (1999765508).  The Tab map
inside the dungeon shows 沃桑小教堂地窖 / 传送点 with camera-only controls.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/dungeon-waypoint-0054"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    a = load("dungeon-a-scan.json")["result"]
    b = load("dungeon-b-scan.json")["result"]
    m = load("dungeon-map-ui.json")
    check("dungeon-a-place", a["place"] == 1999699971, a["place"])
    check("dungeon-b-place", b["place"] == 1999765508, b["place"])
    check("dungeon-travel-changed", a["place"] != b["place"])
    check("dungeon-map-waypoint", any("传送点" in (x.get("text") or "") for x in m["items"] if x["visible"]))
    check("dungeon-map-camera-footer", any("移动地图" in (x.get("text") or "") for x in m["items"] if x["visible"]))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "checks": 5, "evidence_sha256": evidence,
               "note": "waypoint travel inside the cathedral: 1999699971 -> 1999765508; the Tab map only offers camera controls"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("5 dungeon waypoint checks passed")


if __name__ == "__main__":
    main()
