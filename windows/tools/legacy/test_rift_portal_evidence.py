"""Verify the rift obelisk flow end to end through the native pad/click path.

The rift portal spawns on the obelisk's spot with no clickable cylinder, so the
0056 picker retargets a winning hit on that spot to the portal.  The click then
walks to it and operates it, the world changes to the rift place, and leaving
through the main menu returns to town with the quest gone.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/rift-entry3-0056"
BUILD = "536B44FB7894E4583BAAD500028473E8218C0B529020FB4CFA3B3227DAF92F39"
TOWN = 1999503360
RIFT = 1999634434


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(doc):
    return [t["text"] for t in doc["texts"]] if "texts" in doc else [
        o["text"] for o in doc["items"] if o.get("text")]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    checks = 0
    click = load("click-portal.json")
    before = load("scan2.json")["result"]
    after = load("scan3.json")["result"]
    back = load("back-in-town.json")["result"]
    inside_ui = load("inside-ui.json")
    town_ui = load("town-ui.json")
    menu = load("mainmenu.json")
    log = (EVID / "log-entry.txt").read_text("utf-8")

    check("same-build-click", click["build"]["exe_sha256"] == BUILD, click["build"]["exe_sha256"])
    checks += 1

    both = {e["sno"]: e for e in before["entities"]}
    check("obelisk-and-portal-colocated", 364715 in both and 345935 in both
          and abs(both[364715]["distance"] - both[345935]["distance"]) < 0.05, sorted(both))
    check("before-in-town", before["place"] == TOWN and after["place"] == RIFT)
    checks += 2

    check("log-portal-seen", "rift portal 78b000e4 seen at 4.71 radius 0.00" in log)
    check("log-retarget", "retargeted over sno 364715" in log)
    check("log-operate-accepted", "power 30021 at 4.71 -> accepted" in log)
    check("log-portal-hit", "cylinder hit 78b000e4 sno 345935" in log)
    checks += 4

    check("inside-position", abs(after["pos"][0] - 669.4) < 1 and abs(after["pos"][1] - 776.1) < 1, after["pos"])
    texts_inside = " ".join(texts(inside_ui))
    check("inside-hud", "奈非天秘境" in texts_inside and "消灭奈非天秘境守卫的手下" in texts_inside and "0%" in texts_inside)
    check("inside-no-panel", "选择秘境类型" not in texts_inside)
    checks += 3

    check("menu-shows-main", any("主菜单" in t for t in texts(menu)) and any("继续" in t for t in texts(menu)))
    check("back-in-town", back["place"] == TOWN and abs(back["pos"][0] - 308.8) < 1, (back["place"], back["pos"]))
    text_town = " ".join(texts(town_ui))
    check("town-quest-cleared", "消灭奈非天秘境守卫的手下" not in text_town and "奈非天秘境" not in text_town)
    checks += 3

    evidence = {}
    for p in sorted(EVID.iterdir()):
        if p.is_file() and p.suffix in (".json", ".txt"):
            evidence[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (EVID / "summary.json").write_text(json.dumps({
        "scope": __doc__, "build": BUILD, "checks": checks, "evidence_sha256": evidence,
        "result": "obelisk menu -> Nephalem rift accept -> HUD -> portal click entered place "
                  f"{RIFT} -> main-menu continue returned to {TOWN} with the quest cleared",
        "boundary": "the portal retarget is limited to RIFT_PORTAL_SNO 345935; rift progress "
                    "and the guardians were not fought",
    }, ensure_ascii=False, indent=2), "utf-8")
    print(f"{checks} rift portal checks passed")


if __name__ == "__main__":
    raise SystemExit(main())
