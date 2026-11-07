"""Verify Kadala in Act 5 and the insufficient-shard refusal.

The panel opens with 单手/双手神秘武器 at 75 blood shards while the hero holds 25,
so the mouse purchase path runs and the game answers 没有足够的血岩碎片。 with the
balance unchanged - the negative case for an insufficient resource.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act5-kadala-0054"
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


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    panel = load("kadala-panel-ui.json")
    selected = load("kadala-selected-ui.json")
    refused = load("kadala-refused-ui.json")
    for tag, doc in (("panel", panel), ("selected", selected), ("refused", refused)):
        check("kadala-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    joined = " ".join(texts(panel))
    check("kadala-panel-open", "血岩碎片商人" in joined and "神秘武器" in joined)
    check("kadala-cost", "75 {icon:x1_shard}" in joined and "25/500 {icon:x1_shard}" in joined, joined[:120])
    check("kadala-select-footer", "购买" in footer(selected) and "返回" in footer(selected))
    check("kadala-refusal", "没有足够的血岩碎片。" in " ".join(texts(refused)))
    check("kadala-balance-kept", "25/500 {icon:x1_shard}" in " ".join(texts(refused)))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 8, "evidence_sha256": evidence,
               "note": "75-shard item vs 25 held: mouse 购买 shows 没有足够的血岩碎片。 and the balance stays 25/500"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("8 Kadala checks passed")


if __name__ == "__main__":
    main()
