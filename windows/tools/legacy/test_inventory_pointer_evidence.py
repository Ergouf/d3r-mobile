"""Verify live inventory pointer evidence for 0064: right-click, drag and Ctrl transfer."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/native-hotkeys-0063"
BUILD = "E42FFC8643E80191643E3897FF8ACD3B3D7555AF97CC7D54984E4431977D49BF"
ALLOWED = {BUILD, "098B9D0ACE6618698E7BEE4BF3E891BC8E3A681695A2B91DFF91DCCAEF4B1AF5"}
fails = []
checks = 0

def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))

def check(name, cond):
    global checks
    checks += 1
    if not cond:
        fails.append(name)

def result(doc):
    return doc["result"]

def item_loc(doc, gbid):
    for item in result(doc)["items"]:
        if item["gbid"] == gbid:
            return item["loc"]
    return None

def counts(doc):
    return [s["count"] for s in result(doc)["selectors"]]

names = ["right-equip2-before.json", "right-equip2-after.json", "right-restore2-after.json",
         "drag-equip-after.json", "drag-unequip-after.json", "ctrl-before.json",
         "ctrl-deposit-after.json", "ctrl-withdraw-after.json",
         "stash-drag-deposit-after.json", "stash-drag-withdraw-after.json",
         "stash-invalid-drop-after.json"]
docs = {n: load(n) for n in names}
for n, doc in docs.items():
    check("build-" + n, doc["build"]["exe_sha256"] in ALLOWED)

check("right-click-before-bag", item_loc(docs["right-equip2-before.json"], 3382512598)[1:3] == [0, 3])
check("right-click-before-equipped", item_loc(docs["right-equip2-before.json"], 2503951636)[1:] == [4, 0, 0])
check("right-click-equips", item_loc(docs["right-equip2-after.json"], 3382512598)[1:] == [4, 0, 0])
check("right-click-swaps-out", item_loc(docs["right-equip2-after.json"], 2503951636)[1:3] == [0, 3])
check("right-click-restore", item_loc(docs["right-restore2-after.json"], 2503951636)[1:] == [4, 0, 0])
check("drag-equip", item_loc(docs["drag-equip-after.json"], 2503951636)[1:] == [4, 0, 0])
check("drag-unequip", item_loc(docs["drag-unequip-after.json"], 2503951636)[1:3] == [0, 4])
check("ctrl-deposit", counts(docs["ctrl-before.json"])[:2] == [16, 0] and counts(docs["ctrl-deposit-after.json"])[:2] == [15, 1])
check("ctrl-withdraw", counts(docs["ctrl-withdraw-after.json"])[:2] == [16, 0])
check("stash-drag-deposit", counts(docs["stash-drag-deposit-after.json"])[:2] == [15, 1])
check("stash-drag-withdraw", counts(docs["stash-drag-withdraw-after.json"])[:2] == [16, 0])
check("invalid-drop-unchanged", counts(docs["stash-invalid-drop-after.json"])[:2] == [16, 0])
check("right-click-input-is-right", load("right-equip2-input.json")["button"] == "right")

summary = {"checks": checks, "failures": fails, "build": BUILD,
           "scope": "0064 live right-click equip, drag equip/unequip, Ctrl/stash transfer"}
(EVID / "inventory-pointer-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(f"{checks} inventory pointer checks; {len(fails)} failures")
if fails:
    print("FAIL", ", ".join(fails))
raise SystemExit(bool(fails))

