"""Verify terrain occlusion rejects a hidden gate candidate on 0139."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "723331B5C6C4C98136ED585D291C760A8F5A8F295825E48E8319C34EAEB084B6"
fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


before = load("0139-destination-for-occlusion.json")
click = load("0139-occlusion-portal-click.json")
after = load("0139-occlusion-result.json")
log = (EVID / "0139-occlusion.log").read_text(encoding="utf-8")
entities = {entity["sno"]: entity for entity in before["result"]["entities"]}

for label, doc in (("before", before), ("click", click), ("after", after)):
    check(f"{label}-build", doc.get("build", {}).get("exe_sha256") == BUILD, doc.get("build"))
check("before-destination", before["result"]["place"] == 1999634434, before["result"].get("place"))
check("candidate-overlap", set(entities) >= {90419, 175482}, sorted(entities))
check("native-click", click.get("ok") is True and click.get("pid") == before["identity"]["pid"] and
      click.get("screen") == [459, 285], click)
check("terrain-occlusion-log", "door skip 7bb8003c depth 96.35 terrain 94.16" in log, log)
check("hidden-gate-not-prioritized", "New Tristram gate priority 83" not in log, log)
check("visible-portal-hit", "cylinder hit 7bb7003b sno 175482 depth 82.389 terrain 94.164" in log, log)
check("portal-operate", "entity goal 83 handle 7bb7003b" in log and
      "power 30021 at 4.22 -> accepted" in log, log)
check("after-town", after["result"]["place"] == 1999503360, after["result"].get("place"))
check("position-changed", before["result"]["pos"] != after["result"]["pos"],
      {"before": before["result"].get("pos"), "after": after["result"].get("pos")})

summary = {
    "build": BUILD,
    "pid": before["identity"]["pid"],
    "scope": "terrain occlusion rejects hidden gate candidate while visible portal remains interactable",
    "hidden_gate": {"sno": 90419, "depth": 96.35, "terrain": 94.16, "selected": False},
    "visible_portal": {"sno": 175482, "depth": 82.389, "terrain": 94.164, "selected": True},
    "place": {"before": 1999634434, "after": 1999503360},
    "checks": checks,
    "failures": fails,
}
(EVID / "0139-occlusion-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
