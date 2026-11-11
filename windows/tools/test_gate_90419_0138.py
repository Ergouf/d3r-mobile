"""Verify 0138 retargets the overlapping orange portal to the New Tristram gate."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
PATCH = ROOT / "windows/patches/0138-native-new-tristram-gate-priority.patch"
OLD_BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"
NEW_BUILD = "CCFFE18C453945FAE19EC08A0719D1A0B0FE33F5D4961363FB1DE6C18AE71AE6"

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


old_portal = load("gate-90419-portal-click-current.json")
gate_scan = load("0138-gate-live.json")
priority = load("0138-gate-click-priority.json")
logged = load("0138-gate-priority-logged.json")
final_scan = load("0138-gate-final-scan.json")
boot = load("0138-boot-t9.json")
menu = load("0138-mainmenu.json")
town = load("0138-town.json")

check("old-build", old_portal["build"]["exe_sha256"] == OLD_BUILD, old_portal.get("build"))
for name, doc in (("gate-scan", gate_scan), ("priority", priority), ("final-scan", final_scan),
                  ("boot", boot), ("menu", menu), ("town", town)):
    check(f"{name}-new-build", doc["build"]["exe_sha256"] == NEW_BUILD, doc.get("build"))

old_goal = old_portal["state"]["goal"]
check("old-hit-was-orange-portal", old_goal["sno"] == 175482 and
      old_goal["target_place"] == 1999503360, old_goal)
entities = {e["sno"]: e for e in gate_scan["result"]["entities"]}
check("overlap-visible", 175482 in entities and 90419 in entities and
      entities[175482]["distance"] < entities[90419]["distance"], entities)
new_goal = priority["state"]["goal"]
check("new-click-is-gate", priority["actions"][0].get("click") == [850, 420] and
      new_goal["sno"] == 90419 and new_goal["target_place"] == 1999503360,
      {"actions": priority.get("actions"), "goal": new_goal})
logged_goal = logged["state"]["goal"]
check("logged-click-is-gate", logged["result"][0].get("click") == [572, 490] and
      logged_goal["sno"] == 90419, {"result": logged.get("result"), "goal": logged_goal})
formats = [m.get("payload", {}).get("fmt", "") for m in logged.get("logs", []) if m.get("type") == "send"]
check("gate-priority-log", any("New Tristram gate priority" in line for line in formats), formats)
check("gate-operate-attempt", any("native: operate" in line for line in formats), formats)
check("still-in-town", final_scan["result"]["place"] == 1999503360,
      final_scan["result"].get("place"))
check("not-transitioned", new_goal["target_place"] == 1999503360 and
      final_scan["result"]["place"] == 1999503360,
      {"goal": new_goal, "place": final_scan["result"].get("place")})
def ui_text(doc):
    return "\n".join(item.get("text") or "" for item in doc.get("ui", {}).get("items", []))

check("0138-coldboot-anykey", "按任意键" in ui_text(boot), ui_text(boot))
check("0138-main-menu", "主菜单" in ui_text(menu) and "继续" in ui_text(menu), ui_text(menu))
check("0138-town-hud", "新崔斯特姆" in ui_text(town) and "已到达" in ui_text(town), ui_text(town))

patch_text = PATCH.read_text(encoding="utf-8")
check("minimal-patch-shape", "only_sno" in patch_text and "90419u" in patch_text and
      "New Tristram gate priority" in patch_text, patch_text[:500])

summary = {
    "build": NEW_BUILD,
    "pid": final_scan["identity"]["pid"],
    "scope": "0138 overlapping New Tristram orange portal/gate target regression",
    "before": {"sno": 175482, "actor": "0x7d7a00f0"},
    "after": {"sno": 90419, "actor": "0x78bf002f"},
    "place_before": 1999503360,
    "place_after": 1999503360,
    "status": "partial: target priority verified; crossing did not change place",
    "checks": checks,
    "failures": fails,
}
(EVID / "gate-90419-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))