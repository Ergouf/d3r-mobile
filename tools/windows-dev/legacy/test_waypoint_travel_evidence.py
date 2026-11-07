"""Verify waypoint travel on the 0054 build.

The map nodes are custom markers, so a mouse click misses them; the arrow keys do
move the selection (the info panel switches from 新崔斯特姆 to 大教堂一层) and A
travels there, taking the player from place 1999503360 to 1999765508.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/waypoint-travel-0054"
TOWN = 1999503360
CATHEDRAL = 1999765508


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip().replace("\n", " / ") for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    opened = load("map-open-ui.json")
    selected = load("map-selected-ui.json")
    travelled = load("travel-scan.json")["result"]

    check("waypoint-map-open", any(t.startswith("{icon:button1") and "传送" in t for t in texts(opened)))
    check("waypoint-map-town", "新崔斯特姆 / 传送点" in texts(opened))
    check("waypoint-nav-changes", "大教堂一层" in texts(selected))
    check("waypoint-travel-place", travelled["place"] == CATHEDRAL, travelled["place"])
    check("waypoint-travel-moved", abs(travelled["pos"][1] - 820.5) < 30, travelled["pos"])

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "checks": 5, "evidence_sha256": evidence,
               "note": "arrow-key selection switches the destination to 大教堂一层 and A travels to place 1999765508"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("5 waypoint travel checks passed")


if __name__ == "__main__":
    main()
