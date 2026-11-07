"""Verify the 0060 native Nephalem rift entry and the six-affix loadout.

The obelisk menu is opened with an SDL pointer click on the live projection,
the rift is accepted with SDL Space, and the portal is clicked from 4.72
world units - inside the restored 4.8 operate range that 0059 had widened
globally.  The place must change 1999503360 -> 1999699971 and the rift HUD
must show the quest line with 0% progress and hero level 70.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/rift-content-0060"
BUILD = "4F4C0D7265C5E2354B197ECF95B93F3B56D9A19F6DD36145387CF87047B43F13"
TOWN = 1999503360
RIFT = 1999699971


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(doc):
    return [(i.get("text") or "") for i in doc["items"] if i.get("visible") and i.get("text")]


def main():
    checks = []
    def check(name, cond):
        assert cond, name
        checks.append(name)
        print("PASS " + name)

    ident = load("process-identity-3.json")
    check("process-identity", ident["pid"] == 221124 and ident["sha256"] == BUILD and
          ident["path"].lower() == r"d:\games\diabloiii\01001b300b9be000\01001b300b9be000.exe" and
          ident["start"].startswith("2026-11-06T02:08:33"))
    menu = load("r2-obelisk-menu-try.json")
    check("native-obelisk-menu", any("奈非天秘境" in t for t in texts(menu)) and
          any("选择秘境类型" in t for t in texts(menu)))
    click_in = load("r2-obelisk-click.json")
    check("native-obelisk-click", click_in["down"] == 1 and click_in["up"] == 1 and
          click_in["build"]["exe_sha256"] == BUILD)
    portal = load("r2-portal-click.json")
    check("native-portal-click", portal["down"] == 1 and portal["up"] == 1 and
          portal["enginePixel"][0] > 500 and portal["build"]["exe_sha256"] == BUILD)
    inside = load("r2-inside-rift-session.json")
    check("place-changed", inside["player"]["place"] == RIFT and inside["player"]["pos"][0] > 600)
    hud = load("inside-rift-ui.json")
    hud_texts = texts(hud)
    check("rift-hud-quest", any("奈非天秘境" in t for t in hud_texts) and
          any("消灭奈非天秘境守卫的手下" in t for t in hud_texts))
    check("rift-progress-zero", any(t.strip() == "0%" for t in hud_texts))
    check("rift-hero-level-70", any(t.strip() == "70" for t in hud_texts))
    check("legendary-ring-proc", any("全能法戒" in t for t in hud_texts))
    death = load("rift-ui-after-attack.json")
    death_texts = texts(death)
    check("monster-engage-death", any("你死了" in t for t in death_texts) and
          any("你的装备损失了10%的耐久度" in t for t in death_texts))
    revive = load("after-revive3-ui.json")
    check("revive-clears-death", not any("你死了" in t for t in texts(revive)))
    gear = load("maxgear-0060-affix6.json")
    check("six-affix-loadout", len(gear["patched"]) == 13 and
          all(len(p["affixes"]) == 6 for p in gear["patched"]))
    sheet = load("char-sheet-affix6.json")
    sheet_text = "\n".join(texts(sheet))
    check("crit-damage-live", "+106% 暴击伤害" in sheet_text)
    check("attack-speed-live", "+6.0% 攻击速度" in sheet_text)
    check("life-per-hit-live", "击中回复生命" in sheet_text)
    (EVID / "rift-native-entry-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
        "town_place": TOWN, "rift_place": RIFT,
        "portal_distance": 4.72, "operate_range": 4.8,
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} rift native entry checks passed")


if __name__ == "__main__":
    main()
