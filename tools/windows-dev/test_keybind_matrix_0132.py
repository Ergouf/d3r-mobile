"""Verify the 0129 twelve-action keyboard binding matrix evidence."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/takeover-font-startup/0132-bind-all"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
EXE = r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
ACTIONS = [
    "Skill 1", "Skill 2", "Skill 3", "Skill 4", "Potion", "Town portal",
    "Inventory", "Skills", "Journal", "Paragon", "Map", "Pause / Back",
]
REBOUND = ["B", "E", "F", "G", "H", "N", "O", "R", "U", "X", "Y", "5"]
DEFAULTS = ["1", "2", "3", "4", "Q", "T", "C", "S", "J", "P", "M", "Escape"]
EVIDENCE_FILES = [
    "00-Skill-1.json", "01-Skill-2.json", "02-Skill-3.json",
    "03-Skill-4.json", "04-Potion.json", "05-Town-portal.json",
    "06-Inventory.json", "07-Skills.json", "08-Journal.json",
    "09-Paragon.json", "10-Map.json", "11-Pause---Back.json",
]

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def check(name, condition, detail=None):
    global checks
    checks += 1
    if not condition:
        fails.append({"name": name, "detail": detail})


def key_sequence(doc):
    return [entry.get("key") for entry in doc["actions"] if entry.get("type") == "key"]


def visible_text(doc):
    return "\n".join(item.get("text") or "" for item in doc["ui"]["items"])


rebound = load("bindings.json")
check("rebound-build", rebound["build"]["exe_sha256"] == BUILD, rebound["build"])
check("rebound-identity", rebound["identity"].get("exe_path", rebound["identity"].get("exe")) == EXE, rebound["identity"])
check("rebound-overlay-hidden", rebound["shown"] == 0, rebound["shown"])
check("rebound-count", len(rebound["bindings"]) == 12, len(rebound["bindings"]))
check("rebound-actions", [item["action"] for item in rebound["bindings"]] == ACTIONS,
      [item["action"] for item in rebound["bindings"]])
check("rebound-keys", [item["key"] for item in rebound["bindings"]] == REBOUND,
      [item["key"] for item in rebound["bindings"]])
check("rebound-unique", len(set(REBOUND)) == 12, REBOUND)

defaults = load("defaults.json")
check("defaults-build", defaults["build"]["exe_sha256"] == BUILD, defaults["build"])
check("defaults-overlay-hidden", defaults["shown"] == 0, defaults["shown"])
check("defaults-keys", [item["key"] for item in defaults["bindings"]] == DEFAULTS,
      [item["key"] for item in defaults["bindings"]])

for index, name in enumerate(EVIDENCE_FILES):
    doc = load(name)
    sel = ["f2", "down", "down", "enter", "enter"]
    sel[4:4] = ["down"] * index
    expected = sel + [REBOUND[index].lower(), "f2"]
    check(f"{index:02d}-build", doc["build"]["exe_sha256"] == BUILD, doc["build"])
    check(f"{index:02d}-identity", doc["identity"].get("exe_path", doc["identity"].get("exe")) == EXE, doc["identity"])
    check(f"{index:02d}-in-world", doc["state"]["ui_blocked"] == 0, doc["state"])
    check(f"{index:02d}-sequence", key_sequence(doc) == expected, key_sequence(doc))
    check(f"{index:02d}-event-ok", all(entry.get("pushed") == [1, 1] for entry in doc["actions"] if entry.get("type") == "key"),
          [entry for entry in doc["actions"] if entry.get("type") == "key"])
    if index < 5:
        prefix = REBOUND[:index + 1]
        missing = [key for key in prefix if key not in visible_text(doc)]
        check(f"{index:02d}-hud-label", not missing, missing)

restore = load("restore.json")
check("restore-build", restore["build"]["exe_sha256"] == BUILD, restore["build"])
check("restore-in-world", restore["state"]["ui_blocked"] == 0, restore["state"])
check("restore-sequence", key_sequence(restore) == ["f2", "down", "down", "enter"] + ["down"] * 12 + ["enter", "f2"], key_sequence(restore))
default_labels = ["1", "2", "3", "4", "Q"]
check("restore-hud-labels", all(key in visible_text(restore) for key in default_labels), visible_text(restore))

summary = {
    "build": BUILD,
    "scope": "12-action runtime binding matrix: values, persistence evidence, HUD labels, and F2 navigation",
    "checks": checks,
    "actions": len(ACTIONS),
    "failures": fails,
}
(EVID / "0132-keybind-matrix-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(bool(fails))
