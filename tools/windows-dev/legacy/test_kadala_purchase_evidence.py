"""Verify a Kadala purchase once the wallet is topped up.

The profile's blood shards were raised to the 500 cap with local tooling, so the
75-shard mystery weapon can actually be bought: 500/500 -> 425/500 with a -75
delta in the panel, and the save shows 425 shards with one more hero item.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/kadala-purchase-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    panel = load("kadala-panel-ui.json")
    selected = load("kadala-selected-ui.json")
    bought = load("kadala-purchased-ui.json")
    save = load("save-after.json")
    for tag, doc in (("panel", panel), ("selected", selected), ("bought", bought)):
        check("buy-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("buy-panel-balance", "500/500 {icon:x1_shard}" in " ".join(texts(panel)))
    check("buy-selected-footer", any(t.startswith("{icon:button1") and "购买" in t for t in texts(selected)))
    joined = " ".join(texts(bought))
    check("buy-balance-after", "425/500 {icon:x1_shard}" in joined and "-75 {icon:x1_shard}" in joined)
    part = save["partitions"][0]
    check("buy-save-shards", part["currencies"]["1"] == 425 and part["currencies"]["0"] == 851028)
    check("buy-save-item", len(save["heroes"][0]["items"]) == 22)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 8, "evidence_sha256": evidence,
               "note": "500/500 -> 425/500 (-75) and hero items 21 -> 22 after the local shard top-up"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("8 Kadala purchase checks passed")


if __name__ == "__main__":
    main()
