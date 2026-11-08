"""Verify skill 2 is cast toward the live left-side cursor target."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


scene_doc = load("rift-after-skill2-wide2.json")
scene = scene_doc["result"]
before = load("rift-target2-before.json")
cast = load("rift-target2-click-skill2.json")
after = load("rift-target2-after.json")
entry_before = next(e for e in scene["entities"] if e["entry"] == "0x15d7654a0")
hit = cast["actions"][0]
key = cast["actions"][2]
check("scene-build", scene_doc["build"]["exe_sha256"] == BUILD, scene_doc["build"])
for name, doc in (("before", before), ("cast", cast), ("after", after)):
    check(f"{name}-build", doc["build"]["exe_sha256"] == BUILD, doc["build"])
check("target-sno", entry_before["sno"] == before["result"]["sno"] == after["result"]["sno"] == 4982,
      [entry_before["sno"], before["result"]["sno"], after["result"]["sno"]])
check("same-actor", entry_before["id"] == before["result"]["actor"] == after["result"]["actor"],
      [entry_before["id"], before["result"]["actor"], after["result"]["actor"]])
check("leftward-click", hit["type"] == "click" and hit["click"] == [601, 409] and
      hit["click"][0] < scene["entities"][0]["screen"][0], {"click": hit, "player_screen": scene["entities"][0]["screen"]})
check("skill-key", key["type"] == "key" and key["key"] == "2", key)
check("native-dispatch", cast["state"]["ui_blocked"] == 0 and cast["state"]["serial"] >= before["frameCalls"], cast["state"])
hp0 = before["result"]["hp"]["cur"]
hp1 = after["result"]["hp"]["cur"]
check("damage", hp0 == 4966862 and hp1 == 1479204.25 and hp0 - hp1 == 3487657.75, [hp0, hp1])

summary = {
    "build": BUILD,
    "pid": cast["identity"]["pid"],
    "scope": "native SDL click plus skill key 2 toward a left-side live cursor target",
    "target": {"sno": 4982, "actor": after["result"]["actor"]},
    "click": hit["click"],
    "player_screen": scene["entities"][0]["screen"],
    "hp_before": hp0,
    "hp_after": hp1,
    "damage": hp0 - hp1,
    "checks": checks,
    "failures": fails,
}
(EVID / "skill2-direction-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
