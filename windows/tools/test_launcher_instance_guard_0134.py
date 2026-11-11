"""Verify the background launcher refuses a second copy of the installed exe."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108/launcher-instance-guard.json"
LAUNCHER = ROOT / "windows/tools/Launch-Background.ps1"
EXE = "D:\\Games\\DiabloIII\\01001B300B9BE000\\01001B300B9BE000.exe"

fails = []
checks = 0


def check(name, condition, detail=None):
    global checks
    checks += 1
    if not condition:
        fails.append({"name": name, "detail": detail})


guard = json.loads(EVID.read_text(encoding="utf-8"))
launcher = LAUNCHER.read_text(encoding="utf-8")
message = guard.get("message") or ""
check("guard-was-triggered", guard.get("rejected") is True, guard)
check("guard-message", message.startswith("already running: pid=") and f"path={EXE}" in message, message)
check("guard-lists-old-and-new", "196372" in message and "345432" in message, message)
check("launcher-process-lookup", "Get-Process -Name $processName" in launcher, launcher[:1200])
check("launcher-identity-filter", "$_.Path -eq $Exe" in launcher, launcher[:1200])
check("launcher-refuses-start", 'throw "already running:' in launcher, launcher[:1200])
check("launcher-still-sets-immediate", "$env:SNX_VK_IMMEDIATE = '1'" in launcher)
check("launcher-still-restores-env", "Remove-Item Env:SNX_VK_IMMEDIATE" in launcher)

summary = {
    "scope": "single-instance launcher guard observed with two installed-game processes",
    "blocked_pids": [196372, 345432],
    "checks": checks,
    "failures": fails,
}
out = EVID.with_name("launcher-instance-guard-summary.json")
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
