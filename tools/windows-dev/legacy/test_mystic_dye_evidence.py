"""Verify native mouse dye selection, cancellation, payment and restart persistence.

The mystic offers colors for eligible armor without dye items in the bag.
The old empty list was the main-hand item list, not the available color list.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/dye-business-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(state):
    return "\n".join(t["text"] for t in state["texts"])


def main():
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print("PASS " + name)

    weapon = load("dye-mainhand-wheel.json")
    armor = load("dye-torso-wheel.json")
    palette = load("dye-colors-lists.json")
    selected = load("select-water.json")
    cancelled = load("cancel-color.json")
    applied = load("apply-water.json")
    restarted = load("restart-chest-detail.json")
    before = load("save-before.json")
    after = load("save-after-menu.json")
    cold = load("save-after-cold.json")
    final = load("save-final-cold.json")
    cancel_save = load("save-after-cancel-live.json")

    for name, state in (("weapon", weapon), ("armor", armor), ("restart", restarted)):
        check("dye-build-" + name, state["build"]["exe_sha256"] == BUILD)
    check("dye-mainhand-ineligible", "主手" in texts(weapon) and "选择" not in texts(weapon))
    check("dye-chest-eligible", "胸部" in texts(armor) and "选择" in texts(armor))
    check("dye-palette-19", any(i["visible"] and i["rect"] == [662, 157, 862, 489]
                                 and i["rows"] == 19 for i in palette["items"]))
    for name, action in (("select", selected), ("cancel", cancelled), ("apply", applied)):
        check("dye-action-identity-" + name, action["identity_unchanged"]
              and action["build"]["exe_sha256"] == BUILD
              and action["identity"] == applied["identity"])
        check("dye-action-transport-" + name, action["transport"] == "SDL event injection")
    check("dye-grid-row-callback", "row 5 callback 81fb910 -> returned" in selected["log_delta"])
    check("dye-grid-changes-selection", "亮红染料" in texts(selected["before"])
          and "水手染料 - 2160" in texts(selected["after"]))
    check("dye-preview-no-charge", "719203 {icon:gold}" in texts(selected["after"]))
    check("dye-cancel-selection", "没有染色" in texts(cancelled["after"])
          and "对比" in texts(cancelled["after"]))
    check("dye-cancel-no-charge", "719203 {icon:gold}" in texts(cancelled["after"])
          and cancel_save["partitions"][0]["currencies"] == before["partitions"][0]["currencies"])
    check("dye-confirm-footer", "UI footer legend 11 button1 -> queued" in applied["log_delta"])
    check("dye-confirm-ui-result", "水手染料 - 当前外观" in texts(applied["after"])
          and "移除染色" in texts(applied["after"])
          and "717043 {icon:gold}" in texts(applied["after"])
          and "-2160 {icon:gold}" in texts(applied["after"]))
    check("dye-save-gold", before["partitions"][0]["currencies"]["0"] == 719203
          and all(s["partitions"][0]["currencies"]["0"] == 717043 for s in (after, cold, final)))
    check("dye-other-currencies-stable", all(
        {k: v for k, v in s["partitions"][0]["currencies"].items() if k != "0"}
        == {k: v for k, v in before["partitions"][0]["currencies"].items() if k != "0"}
        for s in (after, final)))
    check("dye-items-count", all(len(s["heroes"][0]["items"]) == 23
                                 for s in (before, cancel_save, after, cold, final)))
    def chest(s):
        return next(i for i in s["heroes"][0]["items"] if i["slot"] == 304)
    check("dye-chest-field", chest(before)["gbid"] == 1612257704
          and chest(before)["dye"] == chest(cancel_save)["dye"] == 0
          and all(chest(s)["dye"] == 10 for s in (after, cold, final)))
    def stable_items(s):
        # Runtime entity IDs are regenerated on load; compare persistent metadata.
        return [{k: v for k, v in i.items() if k not in ("id", "dye", "generator_sha256")}
                for i in s["heroes"][0]["items"]]
    check("dye-other-item-fields-stable", stable_items(before) == stable_items(after) == stable_items(final))
    check("dye-only-chest-generator-changed", [i["slot"] for i, j in zip(
        before["heroes"][0]["items"], after["heroes"][0]["items"])
        if i["generator_sha256"] != j["generator_sha256"]] == [304])
    check("dye-no-injected-item", all(i["gbid"] != -234196792 for i in before["heroes"][0]["items"]))
    check("dye-save-roundtrip", all(all(m[k] for k in (
        "complete_parse", "initialized", "protobuf_noop_byte_exact", "xor_noop_byte_exact"))
        for s in (before, after, final) for m in s["files"].values()))
    restart = load("restart-identity.json")
    check("dye-new-process", restart["identity"]["pid"] != applied["identity"]["pid"]
          and restart["identity"]["process_start_ticks"] != applied["identity"]["process_start_ticks"]
          and restart["build"]["exe_sha256"] == BUILD)
    check("dye-restart-ui", restarted["equipment"]["selected"] == 7
          and "水手染料" in texts(restarted) and "717043 {icon:gold}" in texts(restarted))
    check("dye-bag-count-restart", "18/60" in texts(restarted))
    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(EVID.glob("*.json")) if p.name != "summary.json"}
    (EVID / "summary.json").write_text(json.dumps({
        "scope": __doc__, "build": BUILD, "checks": checks, "evidence_sha256": evidence,
        "result": "chest dye_type 0->10, gold -2160; cancelled preview free; survives restart",
        "boundary": "remove-dye footer action was observed but not exercised"
    }, ensure_ascii=False, indent=2), "utf-8")
    print(f"{len(checks)} mystic dye checks passed")


if __name__ == "__main__":
    main()
