"""Verify 0066 PC-habit hotkeys: M map, P paragon, Esc pause/back."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/native-hotkeys-0066"
BUILD = "8D9A1BA7F6470AD4F1B7B2442FF9F00B5BA7F5E064A6AFE46D7EBE0187C5DEEE"
fails = []
checks = 0

def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))

def check(name, cond):
    global checks
    checks += 1
    if not cond:
        fails.append(name)

map_open = load("map-open.json")
esc_map = load("esc-close-map.json")
esc_pause = load("esc-open-pause.json")
paragon = load("p-paragon-ui.json")
for name, doc in (("map", map_open), ("esc-map", esc_map), ("esc-pause", esc_pause), ("paragon", paragon)):
    check("build-" + name, doc["build"]["exe_sha256"] == BUILD)

check("m-opens-map", any(o["name"] == "root.normallayer.map_dialog_mainpage" and o["visible"] for o in map_open["objects"]))
check("m-map-has-title", any(t["text"] for o in map_open["objects"] for t in o["texts"]))
check("esc-closes-map-without-pause", len(esc_map["objects"]) == 0)
check("esc-opens-pause", any(o["name"] == "root.normallayer.consolepause_main" and o["visible"] for o in esc_pause["objects"]))
check("pause-title-visible", any("游戏已暂停" in t["text"] for o in esc_pause["objects"] for t in o["texts"]))
check("p-opens-paragon", any(o["name"] == "root.normallayer.consoleparagon_main" and o["visible"] for o in paragon["objects"]))
check("paragon-content-visible", any(t["text"] for o in paragon["objects"] for t in o["texts"]))

summary = {"checks": checks, "failures": fails, "build": BUILD,
           "scope": "0066 live M map, P paragon, Esc pause/back"}
(EVID / "hotkey-parity-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(f"{checks} PC hotkey checks; {len(fails)} failures")
if fails:
    print("FAIL", ", ".join(fails))
raise SystemExit(bool(fails))
