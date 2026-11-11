"""Verify current-build Act V world-map travel and mouse town-portal return."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
TOWN = 1999503360
ACT5 = 1999765508
ACT5_PORTAL_HUB = 1999831045

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def texts(doc):
    return "\n".join(item.get("text") or "" for item in doc["ui"]["items"])


def check(name, condition, detail=None):
    global checks
    checks += 1
    if not condition:
        fails.append({"name": name, "detail": detail})


def same_build(doc):
    return doc["build"]["exe_sha256"] == BUILD


world = load("world-state.json")
opened = load("act5-map-open.json")
world_tab = load("act5-world-tab.json")
act5 = load("act5-world-act5.json")
selected = load("act5-central-selected.json")
travel = load("act5-central-travel.json")
arrival = load("act5-after-footer-state.json")
portal_hub = load("act5-current-world.json")
return_click = load("act5-portal-return-click2.json")
returned = load("act5-portal-return-result2.json")

for name, doc in (("world", world), ("opened", opened), ("world-tab", world_tab),
                  ("act5", act5), ("selected", selected), ("travel", travel),
                  ("arrival", arrival), ("portal-hub", portal_hub),
                  ("return-click", return_click), ("returned", returned)):
    check(f"{name}-build", same_build(doc), doc.get("build"))

world_place = world.get("place", world.get("result", {}).get("place"))
check("world-start", world_place == TOWN, world_place)
check("map-opened", opened["state"]["ui_blocked"] == 1 and "章节" in texts(opened) and "世界" in texts(opened))
check("world-tab", "高阶天堂" in texts(world_tab) and "威斯特玛" in texts(world_tab))
check("act5-tab", "第五幕" in texts(act5) and "威斯特玛城中区" in texts(act5))
check("central-selected", "威斯特玛城中区" in texts(selected) and "悬赏任务" in texts(selected))
check("footer-native-click", travel["actions"][0]["type"] == "click" and
      travel["actions"][0]["click"] == [285, 648] and travel["state"]["ui_blocked"] == 0,
      travel["actions"][0])
arrival_result = arrival.get("result", arrival)
check("act5-arrived", arrival_result.get("place") == ACT5 and arrival_result.get("ok"), arrival_result)
portal_result = portal_hub.get("result", portal_hub)
check("act5-portal-created", portal_result.get("place") == ACT5_PORTAL_HUB and
      sum(1 for e in portal_result.get("entities", []) if e.get("sno") == 191492) >= 1,
      portal_result)
check("return-click", return_click["actions"][0]["type"] == "click" and
      return_click["actions"][0]["click"] == [640, 340], return_click["actions"][0])
returned_result = returned.get("result", returned)
check("returned-act5-scene", returned_result.get("place") == ACT5, returned_result.get("place"))

# The destination and the user's stored Act V hub use different instance keys,
# so the HUD names and portal transition are part of the acceptance evidence.
arrival_text = "\n".join(item.get("text") or "" for item in load("act5-after-footer-ui.json")["items"])
check("arrival-westmarch-hud", "威斯特玛城中区" in arrival_text, arrival_text)
check("return-state-after-goal", returned_result.get("actor", "").startswith("0x") and returned_result.get("place") == ACT5, returned_result)

summary = {
    "build": BUILD,
    "pid": world["identity"]["pid"],
    "scope": "Act V world-map entry and mouse town-portal return in the current 0129 build",
    "checks": checks,
    "places": {"new_tristram": TOWN, "westmarch": ACT5, "portal_hub": ACT5_PORTAL_HUB},
    "failures": fails,
}
out = EVID / "act5-roundtrip-summary.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
