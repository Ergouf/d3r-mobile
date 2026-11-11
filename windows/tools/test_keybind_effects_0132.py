"""Verify 12 rebound actions survive restart and route old/new keys."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
REBOUND = ["B", "E", "F", "G", "H", "N", "O", "R", "U", "X", "Y", "5"]
DEFAULTS = ["1", "2", "3", "4", "Q", "T", "C", "S", "J", "P", "M", "Escape"]
PANEL_CASES = [
    ("inventory", "物品栏"),
    ("skills", "主动技能会生成愤怒值"),
    ("journal", "当前任务目标"),
    ("paragon", "总点数"),
    ("map", "[拖拽]"),
]
HOTKEY_BASELINE = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 6}

fails = []
checks = 0


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def texts(doc):
    return "\n".join(item.get("text") or "" for item in doc["ui"]["items"])


def check(name, condition, detail=None):
    global checks
    checks += 1
    if not condition:
        fails.append({"name": name, "detail": detail})


def keys(doc):
    return [item["key"] for item in doc["bindings"]]


before = load(EVID / "full-matrix-before-restart/bindings.json")
after = load(EVID / "full-matrix-after-restart/bindings.json")
defaults = load(EVID / "full-matrix-after-restart/defaults.json")
for label, doc, expected in (("before-restart", before, REBOUND),
                             ("after-restart", after, REBOUND),
                             ("restore-default", defaults, DEFAULTS)):
    check(f"{label}-build", doc["build"]["exe_sha256"] == BUILD, doc["build"])
    check(f"{label}-count", len(doc["bindings"]) == 12, len(doc["bindings"]))
    check(f"{label}-keys", keys(doc) == expected, keys(doc))
    check(f"{label}-identity", doc["identity"]["exe_sha256"] == BUILD, doc["identity"])
check("restart-kept-all", keys(before) == keys(after), [keys(before), keys(after)])

for folder, expected_text in PANEL_CASES:
    base = EVID / "full-matrix-after-restart/effects" / folder
    old = load(base / "old.json")
    opened = load(base / "open.json")
    closed = load(base / "close.json")
    check(f"{folder}-old-closed", old["state"]["ui_blocked"] == 0 and expected_text not in texts(old), texts(old))
    check(f"{folder}-new-open", opened["state"]["ui_blocked"] == 1 and expected_text in texts(opened), texts(opened))
    check(f"{folder}-same-key-close", closed["state"]["ui_blocked"] == 0 and expected_text not in texts(closed), texts(closed))

hotkey_dirs = ["skill-1", "skill-2", "skill-3", "skill-4", "potion", "town-portal"]
for index, folder in enumerate(hotkey_dirs):
    base = EVID / "full-matrix-after-restart/hotkeys" / folder
    old = load(base / "old.json")
    new = load(base / "new.json")
    check(f"{folder}-old-inactive", old["state"]["serial"] == HOTKEY_BASELINE[index], old["state"]["serial"])
    if index < 4:
        check(f"{folder}-new-dispatched", new["state"]["serial"] == HOTKEY_BASELINE[index] + 1, new["state"]["serial"])
    elif index == 4:
        check("potion-new-effect", "你的生命值已经全满" in texts(new), texts(new))
    else:
        check("portal-new-effect", "你不能在此区域中那么做" in texts(new), texts(new))

pause_open = load(EVID / "full-matrix-after-restart/hotkeys/pause/open.json")
pause_close = load(EVID / "full-matrix-after-restart/hotkeys/pause/close.json")
check("pause-new-open", pause_open["state"]["ui_blocked"] == 1 and "游戏已暂停" in texts(pause_open), texts(pause_open))
check("pause-new-close", pause_close["state"]["ui_blocked"] == 0 and "游戏已暂停" not in texts(pause_close), texts(pause_close))
escape_doc = load(EVID / "effect-pause/old-esc.json")
check("escape-back-retained", escape_doc["state"]["ui_blocked"] == 1 and "游戏已暂停" in texts(escape_doc), texts(escape_doc))

summary = {
    "build": BUILD,
    "pid": after["identity"]["pid"],
    "scope": ("12 rebound actions after restart; old keys inactive except Escape's intentional "
              "always-available back behavior; new keys dispatch; panels close on the same key; defaults restored"),
    "checks": checks,
    "actions": 12,
    "failures": fails,
}
out = EVID / "full-matrix-after-restart/summary.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
