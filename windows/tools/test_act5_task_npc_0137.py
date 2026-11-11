"""Verify Act V Survivor's Enclave travel and Tyrael dialogue in build 0129."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
WESTMARCH = 2000027656
SURVIVOR = 2000158730

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def texts(doc):
    return "\n".join(item.get("text") or "" for item in doc.get("ui", {}).get("items", []))


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


world = load("act5-task-world-current.json")
city = load("act5-task-travel-current.json")
city_arrival = load("act5-task-arrival-scan.json")
region = load("act5-map-current-region.json")
selected = load("act5-survivor-node-selected.json")
travel = load("act5-survivor-travel.json")
arrival = load("act5-survivor-arrival-scan.json")
hit = load("act5-tyrael-hit.json")
dialogue = load("act5-tyrael-click-current.json")

for name, doc in (("world", world), ("city", city), ("city-arrival", city_arrival),
                  ("region", region), ("selected", selected), ("travel", travel),
                  ("arrival", arrival), ("hit", hit), ("dialogue", dialogue)):
    check(f"{name}-build", doc["build"]["exe_sha256"] == BUILD, doc.get("build"))

check("act5-world-map", "第五幕" in texts(world) and "威斯特玛城中区" in texts(world),
      texts(world))
check("westmarch-arrived-ui", "威斯特玛城中区" in texts(city) and
      "悬赏任务：重生的邪教徒" in texts(city), texts(city))
check("westmarch-place", city_arrival["result"]["place"] == WESTMARCH and
      city_arrival["result"]["player"] == "0x15d9610c0", city_arrival["result"])
check("survivor-region", "第五幕" in texts(region) and "幸存者避难营" in texts(region),
      texts(region))
check("survivor-node", "幸存者避难营" in texts(selected), texts(selected))
check("survivor-arrived-ui", "幸存者避难营" in texts(travel) and
      "传送点" in texts(travel), texts(travel))
check("survivor-place", arrival["result"]["place"] == SURVIVOR and
      arrival["result"]["pos"] == [557.5455322265625, 765.3394165039062, 2.796320676803589],
      arrival["result"])
tyrael_hits = [h for h in hit["result"].get("cylinderHits", []) if h.get("sno") == 114622]
check("tyrael-native-hit", hit["result"].get("screen") == [264, 309] and
      len(tyrael_hits) == 1 and tyrael_hits[0].get("id") == "0x7b5800df" and
      tyrael_hits[0].get("cap") == 30022, hit["result"])
check("tyrael-click", dialogue["actions"][0].get("click") == [264, 309],
      dialogue.get("actions"))
check("tyrael-goal", dialogue["state"]["goal"]["sno"] == 114622 and
      dialogue["state"]["goal"]["target_place"] == SURVIVOR, dialogue.get("state"))
check("tyrael-name", "泰瑞尔" in texts(dialogue), texts(dialogue))
check("tyrael-body", "感谢你来到这里。这儿还有很多悬赏任务可以进行。" in texts(dialogue),
      texts(dialogue))

summary = {
    "build": BUILD,
    "pid": arrival["identity"]["pid"],
    "scope": "Act V Survivor's Enclave travel and native Tyrael dialogue",
    "places": {"westmarch": WESTMARCH, "survivor_enclave": SURVIVOR},
    "npc": {"sno": 114622, "actor": "0x7b5800df", "click": [264, 309]},
    "dialogue_line": "感谢你来到这里。这儿还有很多悬赏任务可以进行。",
    "checks": checks,
    "failures": fails,
}
(EVID / "act5-task-npc-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))