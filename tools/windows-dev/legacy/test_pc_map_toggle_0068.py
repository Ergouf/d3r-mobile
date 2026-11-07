"""Verify 0068 M toggles the map and does not open pause."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0068"
BUILD="19D325FC18F49CF727597CDF977A3096E482CD79F49618034E8C1926526116AE"
fails=[];checks=0
def load(n):return json.loads((EVID/n).read_text(encoding="utf-8"))
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
opened=load("m-open.json");closed=load("m-close.json");proc=json.loads((EVID/"process.json").read_text(encoding="utf-8"))
check("build-process",proc["SHA256"]==BUILD)
check("build-open",opened["build"]["exe_sha256"]==BUILD)
check("build-close",closed["build"]["exe_sha256"]==BUILD)
check("m-opens-map",any(o["name"]=="root.normallayer.map_dialog_mainpage" and o["visible"] for o in opened["objects"]))
check("m-map-title",any(t["text"] for o in opened["objects"] for t in o["texts"]))
check("m-closes-map",len(closed["objects"])==0)
check("m-does-not-open-pause",not any(o["name"]=="root.normallayer.consolepause_main" for o in closed["objects"]))
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0068 M toggles local/waypoint map"}
(EVID/"map-toggle-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} map toggle checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))

