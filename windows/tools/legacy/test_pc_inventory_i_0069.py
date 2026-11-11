"""Verify the native I inventory toggle evidence."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0069"
BUILD="0B4C84EAE3634F70DBA900F6E9AF613CEB161B4C9A7D0E7F905803A088B8F227"
fails=[];checks=0
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
a=json.loads((EVID/"i-open.json").read_text(encoding="utf-8"));b=json.loads((EVID/"i-close.json").read_text(encoding="utf-8"))
check("build-open",a["build"]["exe_sha256"]==BUILD)
check("build-close",b["build"]["exe_sha256"]==BUILD)
check("i-opens-inventory",len(a["objects"])==33)
check("i-closes-inventory",len(b["objects"])==0)
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"native I toggles the inventory"}
(EVID/"i-toggle-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} I toggle checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
