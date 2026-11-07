"""Verify 0071 Alt sends the native item-compare action inside a game UI."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[2];EVID=ROOT/"out/windows/kbm/session/native-hotkeys-0071"
BUILD="1479597A6590D5D5C7CE87D43BE5D80E184B4D6CD39FF6B7CA7212B5AE247997"
fails=[];checks=0
def check(n,c):
 global checks
 checks+=1
 if not c:fails.append(n)
proc=json.loads((EVID/"process.json").read_text(encoding="utf-8"))
log=(ROOT/"D:/Games/DiabloIII/01001B300B9BE000/01001B300B9BE000.log").read_text(encoding="utf-8",errors="replace") if False else (EVID/"alt-compare-game.log").read_text(encoding="utf-8",errors="replace")
bits=[int(m.group(1),16) for line in log.splitlines() for m in [re.search(r"action press queued \(request \d+, bits ([0-9a-f]+)\)",line)] if m]
check("build-process",proc["SHA256"]==BUILD)
check("alt-native-compare-action",0x8 in bits)
check("alt-action-applied",any("bits 00008" in line and "applied" in line for line in log.splitlines()))
check("inventory-open-evidence",(EVID/"alt-before.json").exists())
check("hover-evidence",(EVID/"alt-hover-during.json").exists())
a=json.loads((EVID/"alt-focused-before.json").read_text(encoding="utf-8"));b=json.loads((EVID/"alt-focused-during.json").read_text(encoding="utf-8"));ta=[i["text"] for i in a["items"] if i.get("text")];tb=[i["text"] for i in b["items"] if i.get("text")]
check("alt-adds-ui-text",len(tb)==len(ta)+1)
check("alt-adds-compare-footer",any("对比" in t for t in tb if t not in ta))
summary={"checks":checks,"failures":fails,"build":BUILD,"scope":"0071 Alt sends native button3 and adds the visible compare footer","status":"completed"}
(EVID/"alt-compare-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(f"{checks} Alt compare checks; {len(fails)} failures")
if fails:print("FAIL",", ".join(fails))
raise SystemExit(bool(fails))
