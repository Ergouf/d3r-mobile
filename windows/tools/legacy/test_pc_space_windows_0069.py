"""Verify 0069 Space closes map and character pages without opening pause."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0069"
BUILD="0B4C84EAE3634F70DBA900F6E9AF613CEB161B4C9A7D0E7F905803A088B8F227"
fails=[];checks=0
def load(n):return json.loads((EVID/n).read_text(encoding="utf-8"))
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
mb=load("space-map-before.json");ma=load("space-map-after.json");cb=load("space-char-before.json");ca=load("space-char-after.json");proc=json.loads((EVID/"process.json").read_text(encoding="utf-8"))
check("build-process",proc["SHA256"]==BUILD)
for name,doc in (("map-before",mb),("map-after",ma),("char-before",cb),("char-after",ca)):check("build-"+name,doc["build"]["exe_sha256"]==BUILD)
check("map-visible-before",any(o["name"]=="root.normallayer.map_dialog_mainpage" and o["visible"] for o in mb["objects"]))
check("space-closes-map",len(ma["objects"])==0)
check("inventory-visible-before",any(o["name"]=="root.normallayer.consoleinventoryring_main" and o["visible"] for o in cb["objects"]))
check("space-closes-inventory",len(ca["objects"])==0)
check("no-pause-opened",not any(o["name"]=="root.normallayer.consolepause_main" for o in ma["objects"]+ca["objects"]))
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0069 Space closes map/character pages"}
(EVID/"space-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} Space window checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
