"""Verify 0139 completes New Tristram gate crossing with one native click."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
PATCH = ROOT / "windows/patches/0139-native-new-tristram-gate-chain.patch"
BUILD = "723331B5C6C4C98136ED585D291C760A8F5A8F295825E48E8319C34EAEB084B6"
PATCH_SHA256 = "196c5b3b2a1680d9cc3ea20d032ee3fc6d89e69128de799d44e81aeb9cc88d76"

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


before = load("0139-gate-staged-scan.json")
click = load("0139-gate-single-click.json")
after = load("0139-gate-single-click-result.json")
menu = load("0139-mainmenu-after-space.json")
log = (EVID / "0139-gate-chain.log").read_text(encoding="utf-8")
base = json.loads((ROOT / "windows/patches/base.json").read_text(encoding="utf-8"))
entry = next((item for item in base.get("extra_patches", [])
              if item.get("patch") == PATCH.name), None)
evidence_doc = (ROOT / "windows/docs/KBM-RE-EVIDENCE.md").read_text(encoding="utf-8")

check("0139-patch-present", PATCH.is_file(), str(PATCH))
check("0139-patch-sha256", entry is not None and entry.get("patch_sha256") == PATCH_SHA256, entry)
check("0139-chain-entry", entry is not None and entry.get("changed_files_lf_sha256", {}).get(
    "src/nx/runtime/native_world.c") == "0b8459816b580a671d83fb83c04d64a44bcdbd7194b0a6008f203bfd151f15cd", entry)
# 0139 evidence predates the 0140 install; bind it to the documented 0139 baseline
# rather than the mutable version.py probe anchor.
check("0139-evidence-build-documented", BUILD in evidence_doc, BUILD)

for label, doc in (("before", before), ("click", click), ("after", after), ("menu", menu)):
    check(f"{label}-build", doc.get("build", {}).get("exe_sha256") == BUILD, doc.get("build"))

before_result = before["result"]
before_entities = {entity["sno"]: entity for entity in before_result["entities"]}
check("gate-and-portal-overlap", set(before_entities) >= {90419, 175482}, sorted(before_entities))
check("before-place", before_result["place"] == 1999503360, before_result.get("place"))
check("single-native-click", click.get("ok") is True and click.get("pid") == before["identity"]["pid"] and
      click.get("screen") == [889, 489], click)
check("identity-pinned", before["identity"]["exe"] == after["identity"]["exe"] and
      before["identity"]["create_time_iso"] == after["identity"]["create_time_iso"] and
      before["identity"]["exe_sha256"] == BUILD, before.get("identity"))
check("gate-priority-log", "New Tristram gate priority 80 handle 7a70000a" in log, log)
check("gate-operate-accepted", "native: operate 7a70000a" in log and
      "power 30021 at 4.26 -> accepted" in log, log)
check("paired-portal-chain", "New Tristram gate chained portal 7a71000b" in log and
      before_entities[175482]["id"] == "0x7a71000b", log)
check("portal-operate-accepted", "native: operate 7a71000b" in log and
      "power 30021 at 4.57 -> accepted" in log, log)

check("after-place", after["result"]["place"] == 1999634434, after["result"].get("place"))
check("position-transition", before_result["pos"] != after["result"]["pos"],
      {"before": before_result.get("pos"), "after": after["result"].get("pos")})

def ui_text(doc):
    items = doc.get("items") or doc.get("ui", {}).get("items", [])
    return "\n".join(item.get("text") or "" for item in items)

check("menu-reachable", "主菜单" in ui_text(menu) and "继续" in ui_text(menu), ui_text(menu))

summary = {
    "build": BUILD,
    "pid": before["identity"]["pid"],
    "scope": "0139 New Tristram gate/portal single-click crossing",
    "before": {"pos": before_result["pos"], "place": before_result["place"],
               "gate": "0x7a70000a", "portal": "0x7a71000b"},
    "after": {"pos": after["result"]["pos"], "place": after["result"]["place"]},
    "status": "complete: one native click opened 90419, chained 175482, and changed place",
    "checks": checks,
    "failures": fails,
}
(EVID / "0139-gate-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))
