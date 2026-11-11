"""Verify the no-activate background launch profile and its three cold boots."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/takeover-font-startup"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
fails = []
checks = 0

def check(name, ok):
    global checks
    checks += 1
    if not ok:
        fails.append(name)

launcher = (ROOT / "windows/tools/Launch-Background.ps1").read_text(encoding="utf-8")
check("launcher-immediate", "$env:SNX_VK_IMMEDIATE = '1'" in launcher)
check("launcher-record-off", "$env:SNX_VK_RECORD = '0'" in launcher)
check("launcher-restores-immediate", "Remove-Item Env:SNX_VK_IMMEDIATE" in launcher)
check("launcher-restores-record", "Remove-Item Env:SNX_VK_RECORD" in launcher)
check("launcher-rejects-existing-instance", "already running" in launcher and "Get-Process -Name $processName" in launcher)

for attempt in range(1, 4):
    doc = json.loads((EVID / f"0129-immediate-coldboot-{attempt}.json").read_text(encoding="utf-8"))
    stages = [event.get("stage") for event in doc["events"] if event.get("stage")]
    check(f"attempt-{attempt}-identity", doc["identity"]["exe_sha256"] == BUILD)
    check(f"attempt-{attempt}-success", doc["success"] and stages[-1] == "hud")
    check(f"attempt-{attempt}-sequence", "title" in stages and "menu" in stages)
    check(f"attempt-{attempt}-duration", 20 <= doc["elapsed"] < 35)
single = json.loads((EVID / "continue-single-coldboot.json").read_text(encoding="utf-8"))
single_stages = [event.get("stage") for event in single["events"] if event.get("stage")]
check("single-instance-identity", single["identity"]["exe_sha256"] == BUILD)
check("single-instance-success", single["success"] and single_stages[-1] == "hud")
check("single-instance-sequence", "title" in single_stages and "menu" in single_stages)

summary = {"checks": checks, "failures": fails, "build": BUILD,
           "attempts": 4, "scope": "single-instance no-activate launcher: immediate present + synchronous GPU submission"}
(EVID / "0129-startup-profile-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(bool(fails))
