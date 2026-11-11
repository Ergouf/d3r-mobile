"""Verify native SDL traversal and combat advance a Nephalem Rift in build 0129."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/continue-20261108"
BUILD = "4F05819440313DEE84D83C9DC9D1A78A1481ECD2D07320ADA0F8B0836C9D0F00"

fails = []
checks = 0


def load(name):
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def texts(doc):
    return "\n".join(item.get("text") or "" for item in doc.get("ui", {}).get("items", []))


def check(name, ok, detail=None):
    global checks
    checks += 1
    if not ok:
        fails.append({"name": name, "detail": detail})


start = load("single-boot-town.json")
enter_menu = load("rift-select-nephalem.json")
entered = load("rift-enter-current.json")
inside = load("rift-after-east1.json")
elite_before = load("rift-target1-before.json")
elite_cast = load("rift-target1-skill2.json")
elite_damaged = load("rift-target1-after.json")
elite_damaged2 = load("rift-target1-after2.json")
elite_damaged4 = load("rift-target1-after4.json")
elite_finished = load("rift-elite-finished2.json")
well = load("rift-object-click.json")
small_before = load("rift-418923b-before.json")
small_cast = load("rift-418923b-skill1.json")
cluster = load("rift-west-cluster-skill2.json")
primary_before = load("rift-4982b-before.json")
primary_cast = load("rift-4982b-primary-body.json")
primary_after = load("rift-4982b-after-primary.json")
exit_confirm = load("rift-current-exit-confirm.json")
exit_accept = load("rift-exit-accept-offset.json")
exit_continue = load("rift-current-exit-continue-town.json")
exit_town = load("rift-current-after-exit-town-scan.json")

for name, doc in (("start", start), ("enter-menu", enter_menu), ("entered", entered),
                  ("inside", inside), ("elite-before", elite_before),
                  ("elite-cast", elite_cast), ("elite-damaged", elite_damaged),
                  ("elite-damaged2", elite_damaged2), ("elite-damaged4", elite_damaged4),
                  ("elite-finished", elite_finished), ("well", well),
                  ("small-before", small_before), ("small-cast", small_cast),
                  ("cluster", cluster), ("primary-before", primary_before),
                  ("primary-cast", primary_cast), ("primary-after", primary_after),
                  ("exit-confirm", exit_confirm), ("exit-accept", exit_accept),
                  ("exit-continue", exit_continue), ("exit-town", exit_town)):
    check(f"{name}-build", doc["build"]["exe_sha256"] == BUILD, doc.get("build"))

check("start-town-place", start["result"]["place"] == 1999503360, start["result"].get("place"))
check("obelisk-menu-native-click",
      any(a.get("type") == "click" for a in enter_menu.get("actions", [])),
      enter_menu.get("actions"))
enter_texts = texts(entered)
check("entered-rift-ui", "奈非天秘境" in enter_texts and
      "消灭奈非天秘境守卫的手下" in enter_texts and "0%" in enter_texts, enter_texts)
check("entered-rift-click", entered["actions"][0].get("type") == "click" and
      entered["actions"][0].get("click") == [706, 371], entered["actions"])
check("entered-rift-world", inside["result"]["place"] == 1999699971 and
      inside["result"]["pos"][0] > 1480 and inside["result"]["pos"][1] < 335,
      inside["result"])

hp0 = elite_before["result"]["hp"]["cur"]
hp1 = elite_damaged["result"]["hp"]["cur"]
hp2 = elite_damaged2["result"]["hp"]["cur"]
hp4 = elite_damaged4["result"]["hp"]["cur"]
hp_end = elite_finished["result"]["hp"]["cur"]
check("elite-sno", all(d["result"]["sno"] == 5387 for d in
                       (elite_before, elite_damaged, elite_damaged2, elite_damaged4, elite_finished)))
check("elite-actor-stable", all(d["result"]["actor"] == "0x78d50069" for d in
                                (elite_before, elite_damaged, elite_damaged2, elite_damaged4, elite_finished)))
check("elite-hp-sequence", [hp0, hp1, hp2, hp4, hp_end] ==
      [9514731, 5147494, 2695709.75, 1103115.5, 0], [hp0, hp1, hp2, hp4, hp_end])
check("elite-native-cast", elite_cast["actions"][0].get("click") == [645, 327] and
      elite_cast["actions"][2].get("key") == "2", elite_cast.get("actions"))
check("elite-progress", "1%" in texts(elite_cast), texts(elite_cast))

well_texts = texts(well)
check("well-native-click", well["actions"][0].get("click") == [663, 343] and
      well["state"]["goal"]["sno"] == 373463, well.get("state"))
check("well-progress-and-reward", "5%" in well_texts and "沉思之池奖励" in well_texts, well_texts)

small_hp = small_before["result"]["hp"]["cur"]
check("small-target", small_before["result"]["sno"] == 418923 and small_hp == 803373.125,
      small_before["result"])
check("small-native-cast", small_cast["actions"][0].get("click") == [678.8, 367.5] and
      small_cast["actions"][2].get("key") == "1", small_cast.get("actions"))
check("small-kill-progress", "6%" in texts(small_cast), texts(small_cast))
check("cluster-progress", "7%" in texts(cluster) and
      cluster["actions"][0].get("click") == [612, 375.8] and
      cluster["actions"][2].get("key") == "2", {"ui": texts(cluster), "actions": cluster.get("actions")})
check("primary-body-click", primary_cast["actions"][0].get("click") == [667.3, 444] and
      primary_before["result"]["sno"] == 4982, primary_cast.get("actions"))
check("primary-kill-releases-entity",
      primary_after["result"].get("ok") is False and
      "access violation accessing" in primary_after["result"].get("error", ""),
      primary_after.get("result"))

confirm_text = texts(exit_confirm)
check("exit-confirm-open", exit_confirm["state"]["ui_blocked"] == 1 and
      "你想要退出当前游戏并返回到主菜单吗" in confirm_text and "接受" in confirm_text,
      {"state": exit_confirm.get("state"), "ui": confirm_text})
check("exit-confirm-count", len(exit_confirm["ui"]["items"]) == 683,
      len(exit_confirm["ui"]["items"]))
check("exit-accept-mapped-click", exit_accept["actions"][0].get("click") == [602, 450],
      exit_accept.get("actions"))
check("exit-main-menu", "主菜单" in texts(exit_accept) and
      "你想要退出当前游戏并返回到主菜单吗" not in texts(exit_accept), texts(exit_accept))
check("exit-continue-native-click", exit_continue["actions"][0].get("click") == [296, 260],
      exit_continue.get("actions"))
check("exit-back-world", exit_continue["state"]["ui_blocked"] == 0 and
      "新崔斯特姆" in texts(exit_continue) and "已到达" in texts(exit_continue), texts(exit_continue))
check("exit-town-place", exit_town["result"]["place"] == 1999503360 and
      exit_town["result"]["actor"] == "0x783b007f", exit_town["result"])

progress_docs = (entered, elite_cast, well, small_cast, cluster)
scope_complete = any("100%" in texts(d) for d in progress_docs)
still_kill_minions = all("消灭奈非天秘境守卫的手下" in texts(d) for d in progress_docs)
check("scope-boundary", not scope_complete and still_kill_minions,
      {"100_percent_seen": scope_complete, "still_kill_minions": still_kill_minions})

summary = {
    "build": BUILD,
    "pid": entered["identity"]["pid"],
    "scope": "native SDL obelisk/portal entry, same-actor elite damage, well bonus, 5%->7% progress, and exit to town",
    "place": inside["result"]["place"],
    "exit_town_place": exit_town["result"]["place"],
    "elite": {"sno": 5387, "actor": "0x78d50069",
              "hp_sequence": [hp0, hp1, hp2, hp4, hp_end]},
    "progress": ["0%", "1%", "5%", "6%", "7%"],
    "remaining": ["rift guardian", "100%", "completion reward"],
    "checks": checks,
    "failures": fails,
}
(EVID / "rift-nephalem-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=True))
raise SystemExit(bool(fails))