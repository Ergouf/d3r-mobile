"""Verify 0070 same panel key closes the current character page."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0070"
BUILD="73E9239DA5AC9855730311CCD8D6F7C0FA551DAFA82FC8860121DC71C7ED6836"
fails=[];checks=0
def load(n):return json.loads((EVID/n).read_text(encoding="utf-8"))
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
c_open=load("c-open.json");c_close=load("c-close.json");s_open=load("s-open.json");s_close=load("s-close.json");proc=json.loads((EVID/"process.json").read_text(encoding="utf-8"))
check("build-process",proc["SHA256"]==BUILD)
for name,doc in (("c-open",c_open),("c-close",c_close),("s-open",s_open),("s-close",s_close)):check("build-"+name,doc["build"]["exe_sha256"]==BUILD)
check("c-opens-inventory",len(c_open["objects"])>0)
check("c-closes-inventory",len(c_close["objects"])==0)
check("s-opens-skills",len(s_open["objects"])>0)
check("s-closes-skills",len(s_close["objects"])==0)
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0070 C/S same-key toggle"}
(EVID/"panel-toggle-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} panel toggle checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
