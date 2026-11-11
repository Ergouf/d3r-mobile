"""Verify stack split and keyboard binding evidence."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/takeover-font-startup"
fails = []

def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))

def rubies(name):
    data = load(name)["result"]
    return data["actor"], [x for x in data["items"] if x["sno"] == 437457]

def texts(name):
    return [x.get("text") for x in load(name)["ui"]["items"] if x.get("text")]

def check(name, ok):
    if not ok:
        fails.append(name)

actor, before = rubies("0127-split-before-items.json")
_, after = rubies("0127-split-after-items.json")
_, cancelled = rubies("0127-cancel-after-items.json")
check("before-stack", len(before) == 1 and int(before[0]["stack_hex"], 16) == 3)
check("after-stacks", len(after) == 2 and sorted(int(x["stack_hex"], 16) for x in after) == [1, 2])
check("after-positions", {tuple(x["loc"][1:3]) for x in after} == {(0, 1), (0, 3)})
check("cancel", sorted(int(x["stack_hex"], 16) for x in cancelled) == [1, 2])
check("actor", all(x["loc"][0] == actor for x in before + after + cancelled))
saved = load("0127-split-save.json")
check("save", sorted(x["stack"] for h in saved["heroes"] for x in h["items"] if x["gbid"] == 1019190637) == [1, 2])

bindings = load("0128-bind-persist.json")["bindings"]
check("bind-inventory", bindings[6]["key"] == "H")
check("bind-pause", bindings[11]["key"] == "E")
check("h-open", load("0128-persist-h-open2.json")["state"]["ui_blocked"] == 1 and any("物品栏 {c_white}29/60{/c}" in (x or "") for x in texts("0128-persist-h-open2.json")))
check("c-closed", load("0128-old-c-closed.json")["state"]["ui_blocked"] == 0 and not any("物品栏 {c_white}29/60{/c}" in (x or "") for x in texts("0128-old-c-closed.json")))
check("e-open", load("0128-rebind-pause-open.json")["state"]["ui_blocked"] == 1 and "游戏已暂停" in texts("0128-rebind-pause-open.json"))
check("e-close", load("0128-rebind-pause-close.json")["state"]["ui_blocked"] == 0 and "游戏已暂停" not in texts("0128-rebind-pause-close.json"))
final_bindings = load("0128-final-defaults.json")["bindings"]
check("defaults-restored", final_bindings[6]["key"] == "C" and final_bindings[11]["key"] == "Escape")
check("default-c-open", load("0128-default-c-open.json")["state"]["ui_blocked"] == 1)
check("default-c-close", load("0128-default-c-close.json")["state"]["ui_blocked"] == 0)
check("old-e-noop", load("0128-default-e-noop.json")["state"]["ui_blocked"] == 0)

summary = {"checks": 15, "failures": fails}
(EVID / "0128-stack-rebind-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(bool(fails))