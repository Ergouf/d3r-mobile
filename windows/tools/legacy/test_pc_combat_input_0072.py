"""Verify live Shift stand-still and held-LMB combat evidence on 0072."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0072b"
BUILD="7A8C050BAE186ECA38010B47E1F87BC348C53CAE2ADAB9A1EF704BECE03F3D66"
fails=[];checks=0
def load(n):return json.loads((EVID/n).read_text(encoding="utf-8"))
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
def ent(doc,hid):
 return next((x for x in doc["result"]["entities"] if x["id"]==hid),None)
sb=load("shift-clean-before.json");sa=load("shift-clean-after.json");hb=load("hold-before.json");ha=load("hold-after.json")
check("build-shift-before",sb["build"]["exe_sha256"]==BUILD)
check("build-shift-after",sa["build"]["exe_sha256"]==BUILD)
check("shift-position-unchanged",sb["result"]["pos"]==sa["result"]["pos"])
check("shift-target-before",ent(sb,"0x797c00e2") is not None and ent(sb,"0x797c00e2")["health"]>0)
check("shift-target-removed",ent(sa,"0x797c00e2") is None)
check("hold-target-before",ent(hb,"0x78f100b7") is not None)
check("hold-running",load("hold-attack.json")["dwell_ms"]==1500)
log=(EVID/"combat-game.log").read_text(encoding="utf-8",errors="replace")
check("shift-native-attack-log", ("78f90086" in log or "797c00e2" in log) and "attack" in log)
check("hold-multiple-attacks",log.count("native: attack ")>=2)
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0072 live Shift stand-still and held-LMB attacks"}
(EVID/"combat-input-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} combat input checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
