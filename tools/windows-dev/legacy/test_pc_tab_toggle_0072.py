"""Verify 0072 Tab toggles the map without opening pause."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0072b"
BUILD="7A8C050BAE186ECA38010B47E1F87BC348C53CAE2ADAB9A1EF704BECE03F3D66"
fails=[];checks=0
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
a=json.loads((EVID/"tab-open.json").read_text(encoding="utf-8"));b=json.loads((EVID/"tab-close.json").read_text(encoding="utf-8"));proc=json.loads((EVID/"process.json").read_text(encoding="utf-8"))
check("build-process",proc["SHA256"]==BUILD)
check("build-open",a["build"]["exe_sha256"]==BUILD)
check("build-close",b["build"]["exe_sha256"]==BUILD)
check("tab-opens-map",any(o["name"]=="root.normallayer.map_dialog_mainpage" and o["visible"] for o in a["objects"]))
check("tab-closes-map",len(b["objects"])==0)
check("no-pause-opened",not any(o["name"]=="root.normallayer.consolepause_main" for o in b["objects"]))
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0072 Tab toggles map"}
(EVID/"tab-toggle-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} Tab toggle checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
