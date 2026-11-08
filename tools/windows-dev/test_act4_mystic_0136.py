"""Verify Act IV Bastion travel and Mystic page switching in build 0129."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"

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


opened = load("act4-map-world-current.json")
selected = load("act4-world-selected-current.json")
travel = load("act4-session2-travel.json")
arrival = load("act4-session2-arrival-scan.json")
mystic = load("act4-mystic-click.json")
transmog = load("act4-mystic-transmog-tab.json")
dye = load("act4-mystic-dye-tab.json")
training = load("act4-mystic-training-tab.json")

for name, doc in (("opened", opened), ("selected", selected), ("travel", travel),
                  ("arrival", arrival), ("mystic", mystic), ("transmog", transmog),
                  ("dye", dye), ("training", training)):
    check(f"{name}-build", doc["build"]["exe_sha256"] == BUILD, doc.get("build"))

opened_text = texts(opened)
selected_text = texts(selected)
travel_text = texts(travel)
mystic_text = texts(mystic)
check("act4-world-open", opened["state"]["ui_blocked"] == 1 and
      "世界" in opened_text and "高阶天堂" in opened_text, opened_text)
check("act4-selected", "第四幕" in selected_text and "巴斯廷要塞据点" in selected_text,
      selected_text)
check("act4-travel-state", travel["state"]["ui_blocked"] == 0 and
      "巴斯廷要塞据点" in travel_text and "已到达" in travel_text, travel_text)
check("act4-arrival", arrival["result"]["place"] == 1999699971 and
      arrival["result"]["pos"] == [402.53997802734375, 414.34197998046875, 1.5333667993545532],
      arrival["result"])
check("mystic-native-click", mystic["actions"][0].get("click") == [827, 190] and
      mystic["state"]["goal"]["sno"] == 56948, {"actions": mystic.get("actions"),
                                                "state": mystic.get("state")})
check("mystic-open", "米丽安" in mystic_text and "{c_gold}工匠{/c}" in mystic_text and
      all(tab in mystic_text for tab in ("附魔", "幻化", "染色", "训练")), mystic_text)
check("transmog-tab", transmog["actions"][0].get("click") == [541, 51] and
      "幻化" in texts(transmog), texts(transmog))
check("dye-tab", dye["actions"][0].get("click") == [743, 51] and
      "染料" in texts(dye), texts(dye))
check("training-tab", training["actions"][0].get("click") == [920, 51] and
      "训练秘士来学会新的配方" in texts(training) and "等级" in texts(training), texts(training))
check("service-unchanged-boundary", "720293" in texts(training) and
      "4000" in texts(training), texts(training))

summary = {
    "build": BUILD,
    "pid": arrival["identity"]["pid"],
    "scope": "Act IV world-map travel to Bastion's Keep and native Mystic tab switching",
    "place": arrival["result"]["place"],
    "arrival_player": arrival["result"]["actor"],
    "mystic_sno": 56948,
    "tabs": ["附魔", "幻化", "染料", "训练"],
    "transaction_verified": False,
    "checks": checks,
    "failures": fails,
}
(EVID / "act4-mystic-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))