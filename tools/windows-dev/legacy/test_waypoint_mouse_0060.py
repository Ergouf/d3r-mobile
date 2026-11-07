"""Record the 0060 waypoint-map mouse-selection result.

The Act 5 waypoint (SNO 6442) opens the map with the Westmarch nodes; an SDL
pointer click on the resolved centre of 威斯特玛城中区 (796,404) leaves the
header on 幸存者避难营 and the native UI click probe reports
"no active UI focus", so mouse node selection is still unimplemented.
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

    click = load("click-waypoint.json")
    check("native-waypoint-click", click["down"] == 1 and click["up"] == 1 and
          click["build"]["exe_sha256"] == BUILD)
    opened = load("waypoint-map.json")
    opened_text = "\n".join(texts(opened))
    check("map-opened", "幸存者避难营" in opened_text and "传送点" in opened_text)
    check("act5-nodes", all(n in opened_text for n in
                            ("幸存者避难营", "威斯特玛城中区", "威斯特玛上城区")))
    after = load("map-after-node-click.json")
    after_text = "\n".join(texts(after))
    check("mouse-node-does-not-select", "威斯特玛城中区" in after_text and
          after_text.count("幸存者避难营") >= 1 and "威斯特玛城中区\n传送点" not in after_text)
    native = load("native-node-click.json")["result"]
    check("native-probe-no-focus", native["ok"] is False and native["reason"] == "no active UI focus")
    (EVID / "waypoint-mouse-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
        "node_click_pixel": [796, 404], "selected_after_click": "幸存者避难营",
        "status": "negative: mouse node selection still missing",
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} waypoint mouse checks passed")


if __name__ == "__main__":
    main()
