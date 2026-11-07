"""Verify the mouse-only mystic transmog loop and the cancel path.

The 0050 build selects an appearance by clicking a row of the live appearance
list (generic native list control, callback 0x81FB910), confirms through the
footer legend, and cancels with B without charging.  Every check reads the
recorded UI tree and the cold save checkpoints of that run.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/mystic-transmog-mouse-0050"
BUILD = "52ECAE7B05F971CD50A9E91A41BE1F35C1AAE42164D2BC47DBF073404D8BE053"
HERO_SLOT = 336


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [x["text"] for x in d["items"] if x.get("text")]


def footer(d):
    for t in texts(d):
        if t.startswith("{icon:button"):
            return t
    raise AssertionError("no footer legend in " + str(d.get("pid")))


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def hero_items(snapshot):
    for hero in snapshot["heroes"]:
        return hero["items"]
    raise AssertionError("no hero in snapshot")


def main():
    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    listed = load("list-open-ui.json")
    row = load("row-selected-ui.json")
    applied = load("applied-ui.json")
    detail = load("item-detail-ui.json")
    cancel_row = load("cancel-row-ui.json")
    cancel = load("cancel-ui.json")
    cancel_all = load("cancel-all-ui.json")
    before = load("save-before.json")
    after = load("save-after.json")
    after_cancel = load("save-after-cancel.json")

    for name, doc in (("list", listed), ("row", row), ("applied", applied), ("detail", detail),
                      ("cancel-row", cancel_row), ("cancel", cancel), ("cancel-all", cancel_all)):
        check("transmog-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("transmog-list-open-footer", footer(listed).strip().endswith("返回") and "选择" not in footer(listed))
    check("transmog-row-click-selects", "幻化" in footer(row) and footer(row).strip().endswith("返回"))
    check("transmog-apply-gold-ui", "865474 {icon:gold}" in " ".join(texts(applied)) and
          "-10000 {icon:gold}" in " ".join(texts(applied)))
    check("transmog-item-detail", any("幻化：" in t and "派维德小刀" in t for t in texts(detail)))
    check("transmog-cancel-row-selects", "幻化" in footer(cancel_row))
    check("transmog-cancel-footer", "选择" in footer(cancel) and "对比" in footer(cancel))
    check("transmog-cancel-no-charge", "865474 {icon:gold}" in " ".join(texts(cancel_all)) and
          "-10000 {icon:gold}" not in " ".join(texts(cancel_all)))

    items_before, items_after, items_cancel = hero_items(before), hero_items(after), hero_items(after_cancel)
    main_before = [i for i in items_before if i["slot"] == HERO_SLOT][0]
    main_after = [i for i in items_after if i["slot"] == HERO_SLOT][0]
    main_cancel = [i for i in items_cancel if i["slot"] == HERO_SLOT][0]
    check("transmog-save-gold", before["partitions"][0]["currencies"]["0"] == 875474 and
          after["partitions"][0]["currencies"]["0"] == 865474 and
          after_cancel["partitions"][0]["currencies"]["0"] == 865474)
    check("transmog-save-field", main_before["transmog"] == -1 and
          main_after["transmog"] == -1303413123 and main_cancel["transmog"] == -1303413123)
    check("transmog-items-stable", len(items_before) == len(items_after) == len(items_cancel) == 21)

    summary = {"scope": __doc__, "build": BUILD, "checks": 17, "evidence_sha256": evidence,
               "note": "mouse row click + footer confirm applied -1303413123 for -10000 gold; B cancelled row 6 with no charge"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("17 transmog mouse checks passed")


if __name__ == "__main__":
    main()


