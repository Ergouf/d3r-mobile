"""Verify four serial background cold boots on the current 0139 build."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "723331B5C6C4C98136ED585D291C760A8F5A8F295825E48E8319C34EAEB084B6"
EXE = Path(r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe")
fails = []
checks = 0


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


data = json.loads((EVID / "0139-coldboot-summary.json").read_text(encoding="utf-8"))
attempts = data.get("attempts", [])
check("build", data.get("build") == BUILD, data.get("build"))
check("summary-count", data.get("total") == 4 and data.get("passed") == 4, data)
check("attempt-count", len(attempts) == 4, attempts)
check("unique-pids", len({row.get("pid") for row in attempts}) == 4, [row.get("pid") for row in attempts])
for row in attempts:
    number = row.get("attempt")
    identity = row.get("identity", {})
    title = row.get("title_seconds")
    menu = row.get("menu_seconds")
    world = row.get("world_seconds")
    check(f"attempt-{number}-passed", row.get("status") == "passed" and row.get("title_seen") and
          row.get("menu_seen") and row.get("world_seen"), row)
    check(f"attempt-{number}-identity", Path(identity.get("exe", "")).resolve() == EXE.resolve() and
          identity.get("expected_exe") == str(EXE) and identity.get("exe_sha256") == BUILD, identity)
    check(f"attempt-{number}-timing", isinstance(title, (int, float)) and isinstance(menu, (int, float)) and
          isinstance(world, (int, float)) and 0 < title < menu < world and title < 30 and menu < 35 and world < 40,
          {"title": title, "menu": menu, "world": world})

summary = {
    "build": BUILD,
    "scope": "four serial no-activate background cold boots through title, main menu, and world HUD",
    "attempts": len(attempts),
    "timing_seconds": [{key: row.get(key) for key in ("title_seconds", "menu_seconds", "world_seconds")}
                       for row in attempts],
    "checks": checks,
    "failures": fails,
}
(EVID / "0139-startup-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
