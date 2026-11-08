"""Verify CAP=0 town-portal routing on build 0129."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/takeover-font-startup"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
fails = []

def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))

def check(name, ok):
    if not ok:
        fails.append(name)

before = load("0130-town-portal-scan2.json")["result"]
forced = load("0130-cap0-input.json")
after = load("0130-cap0-result.json")["result"]
check("build", forced["build"]["exe_sha256"] == BUILD)
check("before-place", before["place"] == 1999503360)
check("portal-visible", any(e["sno"] == 191492 and e["type"] == 2 for e in before["entities"]))
check("sdl-pushed", forced["sent"][0]["pushed"] == [1, 1])
check("cap-forced-zero", bool(forced["cap_hits"]) and all(h["sno"] == 191492 for h in forced["cap_hits"]))
check("after-place", after["place"] == 1999634434)
summary = {"checks": 6, "failures": fails, "build": BUILD, "place": [1999503360, 1999634434],
           "portal_sno": 191492, "forced_cap": 0,
           "scope": "town portal click despite CAP query result 0"}
(EVID / "0130-town-portal-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(bool(fails))