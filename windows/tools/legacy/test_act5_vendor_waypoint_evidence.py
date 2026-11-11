"""Verify Victor's Act 5 sale/buyback and the native waypoint round trip."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act5-switch-0057"


def main():
    used, checks = {}, []

    def load(name):
        path = EVID / (name + ".json")
        used[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text("utf-8"))

    def check(name, condition):
        assert condition, name
        checks.append(name)
        print("PASS " + name)

    def texts(name):
        return [i["text"] for i in load(name)["items"] if i.get("visible") and i.get("text")]

    def gold(name):
        values = [int(re.fullmatch(r"(\d+) \{icon:gold\}", t)[1])
                  for t in texts(name) if re.fullmatch(r"(\d+) \{icon:gold\}", t)]
        return max(values)

    names = load("npc-names")["result"]["names"]
    check("act5-specific-vendor", any(e["sno"] == 309718 and e["text"] == "X1_A5_UniqueVendor_InnKeeper" for e in names))
    check("victor-shop-opened", "军需官维克多" in texts("innkeeper-ui")
          and all(t in texts("innkeeper-ui") for t in ["购买", "出售", "修复", "回购"]))
    sale, buyback = load("vendor-sell-state"), load("vendor-buyback-state")
    check("native-service-pages", sale["groupIndex"] == buyback["groupIndex"] == 2
          and sale["selected"] == 1 and buyback["selected"] == 3
          and sale["vendor"]["controller"] == buyback["vendor"]["controller"])
    g0, g1, g2 = [gold(n) for n in ["vendor-before-sell", "vendor-sold", "vendor-buyback-done"]]
    check("sale-credit", g0 == 717043 and g1 - g0 == 509)
    check("buyback-debit-and-net-zero", g1 - g2 == 509 and g2 == g0)
    check("mouse-transaction-actions", all(load(n)["down"] and load(n)["up"] for n in
          ["vendor-sell-tab-click", "vendor-sell-confirm", "vendor-buyback-tab-click", "vendor-buyback-confirm"]))
    town_doc, away_doc, back_doc = [load(n) for n in ["scene-all", "map-teleport-place", "waypoint-return-place"]]
    town, away, back = [d["result"] for d in [town_doc, away_doc, back_doc]]
    check("same-evidence-build", town_doc["build"] == away_doc["build"] == back_doc["build"] == sale["build"])
    check("correct-town-waypoint-sno", any(e["sno"] == 6442 and e["place"] == town["place"] for e in town["entities"]))
    check("travel-and-return-places", town["place"] == back["place"] == 1999503360 and away["place"] == 2000027656)
    check("same-player-round-trip", town["actor"] == away["actor"] == back["actor"])
    check("destination-ui-confirmed", any("混沌要塞二层" in t for t in texts("map-teleport-hud"))
          and any("幸存者避难营" in t for t in texts("waypoint-return-hud")))
    check("native-mouse-return-confirm", load("fortress-map-return-confirm")["down"]
          and load("fortress-map-return-confirm")["up"])
    summary = {"scope": __doc__, "checks": checks, "gold": [g0, g1, g2],
               "places": [town["place"], away["place"], back["place"]], "build": sale["build"],
               "evidence_sha256": used,
               "boundary": "Map node selection still uses keyboard axes; direct map-node mouse selection is unimplemented."}
    (EVID / "vendor-waypoint-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"{len(checks)} Act 5 vendor/waypoint checks passed")


if __name__ == "__main__":
    main()
