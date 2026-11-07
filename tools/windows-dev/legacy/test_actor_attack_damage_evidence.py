"""Replay the 0058 SDL mouse attack's live HP evidence and dead-hero guard."""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/actor-attack-0058"


def main():
    used = {}

    def load(name):
        path = EVID / name
        used[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text("utf-8-sig"))

    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)
        print("PASS " + name)

    before_doc = load("skeleton-native-before.json")
    after_doc = load("skeleton-native-after.json")
    click = load("skeleton-native-click.json")
    identity = load("process-identity.json")
    before, after = before_doc["result"], after_doc["result"]
    check("isolated-read-probes", all(d["result"].get("cpu_isolated") for d in [before_doc, after_doc]))
    check("same-world-and-hero", before["place"] == after["place"] == 1999896582 and before["actor"] == after["actor"])
    check("same-recorded-build", before_doc["build"] == after_doc["build"] == click["build"])
    check("running-image-identity", identity["sha256"] == click["build"]["exe_sha256"] and identity["pid"] == 8168
          and identity["exe"].lower() == r"d:\games\diabloiii\01001b300b9be000\01001b300b9be000.exe"
          and identity["creation"].startswith("2026-11-05T20:53:56"))
    target_id = click["target"]["id"]
    t0 = next(e for e in before["entities"] if e["id"] == target_id)
    t1 = next(e for e in after["entities"] if e["id"] == target_id)
    check("same-live-monster", t0["type"] == t1["type"] == 1 and t0["sno"] == t1["sno"] == 312300)
    check("targeted-sdl-pair", click["click"]["down"] and click["click"]["up"]
          and click["click"]["enginePixel"] == [t0["screen"][0], t0["screen"][1] - 25])
    hp0, hp1 = (t["attrs"]["Hitpoints_Cur"] for t in [t0, t1])
    check("observable-monster-damage", 0 < hp1 < hp0 and hp0 - hp1 == 21834.3125)
    check("unchanged-monster-max-hp", t0["attrs"]["Hitpoints_Max_Total"] == t1["attrs"]["Hitpoints_Max_Total"])
    hero_hp = [next(e for e in s["entities"] if e["id"] == s["actor"])["attrs"]["Hitpoints_Cur"] for s in [before, after]]
    check("hero-survives-the-attack", hero_hp == [16216, 16216])
    log_path = EVID / "game-after-mouse-damage.log"
    log = log_path.read_text("utf-8")
    used[log_path.name] = hashlib.sha256(log_path.read_bytes()).hexdigest()
    controller = struct.unpack_from("<I", bytes.fromhex(t0["bytes"]), 0x14)[0]
    check("native-actor-path-and-controller", controller != int(target_id, 16)
          and re.search(rf"native: attack {target_id[2:]} power 285903 path 1 controller {controller:08x} .* -> 1", log))
    check("mouse-pick-correlates-with-attack", f"native: cylinder hit {target_id[2:]} sno 312300" in log
          and f"native: entity goal 42 attack {target_id[2:]} power 285903" in log)
    dead = load("monster-mouse-after.json")["result"]
    check("dead-hero-click-rejected", next(e for e in dead["entities"] if e["id"] == dead["actor"])["attrs"]["Hitpoints_Cur"] == 0
          and "native: world pointer 18 blocked (hero dead)" in log and "native: entity goal 18 " not in log)
    cold = load("save-final-cold.json")
    hero = next(h for h in cold["heroes"] if h["file"] == "9af81ba794cf5b64.dat")
    restored = next(i for i in hero["items"] if i["slot"] == 336)
    check("original-main-hand-restored", restored["gbid"] == -1303415302 and restored["transmog"] == -1303413123
          and restored["seed"] == 1049721745)
    account = next(p for p in cold["partitions"] if p["id"] == 0)
    check("item-counts-and-fixture-resources", len(hero["items"]) == 23 and len(account["items"]) == 3
          and account["crafter_levels"] == [4, 9, 10, 0]
          and [account["currencies"][str(i)] for i in [1, 3, 4, 5]] == [425, 903, 895, 948])
    final_ui = load("restore-original-selected.json")
    check("final-gold-matches-cold-save", account["currencies"]["0"] == 717579
          and any("717579 {icon:gold}" in (i.get("text") or "") for i in final_ui["items"]))
    summary = {"scope": __doc__, "build": click["build"], "checks": checks, "target": target_id,
               "hp_before": hp0, "hp_after": hp1, "damage": hp0 - hp1, "hero_hp": hero_hp,
               "evidence_sha256": used,
               "boundary": "Basic targeted attack only; individual skill direction, powers/cooldowns and rift progress remain unverified."}
    (EVID / "damage-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} actor damage checks passed")


if __name__ == "__main__":
    main()
