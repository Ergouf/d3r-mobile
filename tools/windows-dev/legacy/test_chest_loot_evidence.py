"""Verify the chest-specific range gate, chest opening, and ground pickup."""

from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/maxgear-0059"
BUILD = "B18FEFD0A9745FFB62992C646FC8454B4E7F58F42A670D4AC6340BBF06E1C6BE"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(i.get("text") or "") for i in d["items"] if i.get("visible") and i.get("text")]


def main():
    checks = []
    def check(name, cond):
        assert cond, name
        checks.append(name)
        print("PASS " + name)

    ident = load("process-identity.json")
    click = load("open-62865-range.json")
    scene = load("open-62865-result.json")["result"]
    before = load("chest-drop-bag-before.json")
    after = load("chest-drop-bag-after1.json")
    names = load("chest-drops.json")["result"]["names"]
    log = (EVID / "game-chest-loot.log").read_text("utf-8")
    check("process-identity", ident["pid"] == 98792 and ident["sha256"] == BUILD and
          ident["exe"].lower() == r"d:\games\diabloiii\01001b300b9be000\01001b300b9be000.exe" and
          ident["creation"].startswith("2026-11-05T23:17:35"))
    check("native-sdl-click", click["down"] and click["up"] and click["enginePixel"] == [536, 380] and click["build"]["exe_sha256"] == BUILD)
    chest = next(e for e in scene["entities"] if e["sno"] == 62865)
    check("chest-radius-boundary", chest["id"] == "0x78bc00e5" and abs(chest["distance"] - 6.19) < 0.1)
    check("operate-log", "native: cylinder hit 78bc00e5 sno 62865" in log and
          "native: entity goal 20 operate 78bc00e5 power 30021 at 6.19 -> accepted" in log)
    drops = [e for e in load("chest-drop1-after.json")["result"]["entities"] if e["type"] == 8]
    check("chest-created-two-ground-items", {e["sno"] for e in drops} == {367158, 367162})
    check("drop-assets", {n["sno"]: n["text"] for n in names} ==
          {367158: "x1_bow_norm_base_flippy_02", 367162: "x1_Staff_norm_base_02"})
    check("bag-before", any("物品栏 {c_white}25/60{/c}" in t for t in texts(before)))
    check("bag-after", any("物品栏 {c_white}26/60{/c}" in t for t in texts(after)))
    check("picked-item-visible", any("标靶炽焰" in t for t in texts(after)))
    check("mouse-pick-build", load("pick-chest-drop1.json")["build"]["exe_sha256"] == BUILD)
    patch = (ROOT / "patches/windows/0060-native-chest-specific-range.patch").read_text("utf-8")
    base = json.loads((ROOT / "patches/windows/base.json").read_text("utf-8"))
    check("range-patch", "+#define OPERATE_RANGE 4.8f" in patch and "case 62865u:" in patch and
          "fmaxf(long_interact_sno(g_goal.sno) ? 6.2f : OPERATE_RANGE," in patch and
          any(p["patch"] == "0060-native-chest-specific-range.patch" for p in base["extra_patches"]))
    check("portal-not-widened", "+#define RIFT_PORTAL_SNO 345935u" not in patch)
    check("patch-chain-pass", "PASS" in (ROOT / "out/windows/kbm/session/rift-content-0059/patch-chain-0060.txt").read_text("utf-8").splitlines()[-1])
    (EVID / "chest-loot-summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "build": BUILD,
        "operate_distance": chest["distance"], "drops": sorted(e["sno"] for e in drops),
        "bag": [25, 26], "item": "标靶炽焰"
    }, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} chest loot checks passed")

if __name__ == "__main__":
    main()

