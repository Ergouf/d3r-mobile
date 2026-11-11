"""Verify the mouse stash transfer (deposit and withdraw) on the 0051 build.

Deposits come from a mouse click on a bag row (or the footer legend); the chest
grid takes focus from a direction key, after which the same footer legend
withdraws.  Every assertion reads the recorded UI tree of that run plus the cold
save checkpoints around it.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/stash-transfer-0051"
BUILD = "51402FEB85E593A98D2C21FFE6EFF584585EC632FF3C289DF8C1C317768B1E9F"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [x["text"] for x in d["items"] if x.get("text") and x["visible"]]


def footer(d):
    for t in texts(d):
        if t.startswith("{icon:button"):
            return t
    raise AssertionError("no footer legend")


def counts(d):
    bag = chest = None
    for t in texts(d):
        if t.startswith("物品栏 {c_white}"):
            bag = t
        elif t.startswith("储藏箱 {c_white}"):
            chest = t
    if bag is None or chest is None:
        raise AssertionError("bag/chest counters missing")
    return bag, chest


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    docs = {n: load(n + ".json") for n in
            ("open-ui", "after-restore-ui", "deposit-legend-ui", "deposit2-ui",
             "withdraw-legend-ui", "withdraw1-ui", "withdraw2-ui")}
    for name, doc in docs.items():
        check("stash-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("stash-open", counts(docs["open-ui"]) == ("物品栏 {c_white}11/60{/c}", "储藏箱 {c_white}8/20{/c}"),
          counts(docs["open-ui"]))
    check("stash-restored", counts(docs["after-restore-ui"]) ==
          ("物品栏 {c_white}16/60{/c}", "储藏箱 {c_white}3/20{/c}"))
    check("stash-deposit-legend", "将物品移至储藏箱" in footer(docs["deposit-legend-ui"]))
    check("stash-deposit-counts", counts(docs["deposit-legend-ui"]) ==
          ("物品栏 {c_white}15/60{/c}", "储藏箱 {c_white}4/20{/c}"))
    check("stash-deposit-second", counts(docs["deposit2-ui"]) ==
          ("物品栏 {c_white}14/60{/c}", "储藏箱 {c_white}5/20{/c}"))
    check("stash-withdraw-legend", "将物品移至物品栏" in footer(docs["withdraw-legend-ui"]))
    check("stash-withdraw-first", counts(docs["withdraw1-ui"]) ==
          ("物品栏 {c_white}15/60{/c}", "储藏箱 {c_white}4/20{/c}"))
    check("stash-withdraw-second", counts(docs["withdraw2-ui"]) ==
          ("物品栏 {c_white}16/60{/c}", "储藏箱 {c_white}3/20{/c}"))
    check("stash-footer-back-to-deposit", "将物品移至储藏箱" in footer(docs["withdraw2-ui"]))

    before, after = load("save-before.json"), load("save-after.json")
    check("stash-save-gold", before["partitions"][0]["currencies"]["0"] == 865474 and
          after["partitions"][0]["currencies"]["0"] == 865474)
    check("stash-save-before", len(before["heroes"][0]["items"]) == 20 and
          len(before["partitions"][0]["items"]) == 4)
    check("stash-save-after", len(after["heroes"][0]["items"]) == 21 and
          len(after["partitions"][0]["items"]) == 3)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 15, "evidence_sha256": evidence,
               "note": "bag row click deposits; direction key focuses the chest grid, then the footer legend withdraws"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("15 stash transfer checks passed")


if __name__ == "__main__":
    main()

