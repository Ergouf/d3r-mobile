"""Verify 0067 skill-bar digits and Space close-page input."""
from pathlib import Path
import json, re
ROOT=Path(__file__).resolve().parents[2]
EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0067"
BUILD="D57DF26075029C8F941A6B783873E12CD343FC1AAA744F3DEBAE4211C076ADEB"
fails=[];checks=0
def load(n):return json.loads((EVID/n).read_text(encoding="utf-8"))
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
before=load("space-before.json");after=load("space-after.json");proc=json.loads((EVID/"process.json").read_text(encoding="utf-8"))
check("build-process",proc["SHA256"]==BUILD)
check("build-before",before["build"]["exe_sha256"]==BUILD)
check("build-after",after["build"]["exe_sha256"]==BUILD)
check("inventory-visible-before",any(o["name"]=="root.normallayer.consoleinventoryring_main" and o["visible"] for o in before["objects"]))
check("space-closes-inventory",len(after["objects"])==0)
lines=(EVID/"skillbar-game.log").read_text(encoding="utf-8",errors="replace").splitlines()
queued=[int(m.group(1),16) for line in lines for m in [re.search(r"action press queued \(request \d+, bits ([0-9a-f]+)\)",line)] if m]
check("four-digit-actions",queued[-4:]==[0x8,0x4,0x10,0x20])
check("digit-1-slot-x",queued[-4]==0x8)
check("digit-2-slot-y",queued[-3]==0x4)
check("digit-3-slot-l",queued[-2]==0x10)
check("digit-4-slot-r",queued[-1]==0x20)
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0067 PC skill digits to loadout slots 3-6; Space closes character page"}
(EVID/"skillbar-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} skillbar/Space checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
