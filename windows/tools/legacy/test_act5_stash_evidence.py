"""Verify the Act 5 shared chest round trip on the 0054 build.

Bag row click selects, the footer legend deposits (16/60 -> 15/60, 3/20 -> 4/20),
a direction key focuses the chest grid so the footer legend withdraws again
(15/60 -> 16/60, 4/20 -> 3/20), leaving the save unchanged.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act5-stash-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def footer(d):
    for t in texts(d):
        if t.startswith("{icon:button"):
            return t
    raise AssertionError("no footer")


def counts(d):
    bag = [t for t in texts(d) if t.startswith("物品栏 {c_white}")]
    chest = [t for t in texts(d) if t.startswith("储藏箱 {c_white}")]
    assert bag and chest, "counters missing"
    return bag[0], chest[0]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    docs = {n: load(n + ".json") for n in
            ("stash-open-ui", "stash-selected-ui", "stash-deposited-ui", "grid-focus-ui", "stash-withdrawn-ui")}
    for name, doc in docs.items():
        check("act5-stash-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("act5-stash-open", counts(docs["stash-open-ui"]) == ("物品栏 {c_white}16/60{/c}", "储藏箱 {c_white}3/20{/c}"),
          counts(docs["stash-open-ui"]))
    check("act5-stash-selected", "将物品移至储藏箱" in footer(docs["stash-selected-ui"]))
    check("act5-stash-deposited", counts(docs["stash-deposited-ui"]) ==
          ("物品栏 {c_white}15/60{/c}", "储藏箱 {c_white}4/20{/c}"))
    check("act5-stash-grid-focus", "将物品移至物品栏" in footer(docs["grid-focus-ui"]))
    check("act5-stash-withdrawn", counts(docs["stash-withdrawn-ui"]) ==
          ("物品栏 {c_white}16/60{/c}", "储藏箱 {c_white}3/20{/c}"))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 10, "evidence_sha256": evidence,
               "note": "16/3 -> 15/4 -> 16/3 in Westmarch with the mouse footer legend and one direction key"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("10 Act 5 stash checks passed")


if __name__ == "__main__":
    main()
