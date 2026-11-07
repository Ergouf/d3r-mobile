"""Record the historical failure of three injected dye candidates.

Each variant cloned the accepted gem (GBID 1019190636) and only swapped the gbid
to the verified Golden Dye (-234196792), differing in item_quality_level.  After
installing each one the main-hand item list has rows=0, the bag stays at 18/60,
and the save written by the game is back to 23 items. This does not establish
that dyeing needs inventory dyes: test_mystic_dye_evidence.py verifies that
selecting eligible armor opens the mystic's built-in color palette.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/dye-injection-0054"
BAG_LIST = [373, 130, 622, 590]


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def eligible_item_rows(doc):
    for item in doc["items"]:
        if item.get("rect") == BAG_LIST:
            return item.get("rows")
    raise AssertionError("eligible item list widget missing")


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    manifest = load("candidates-manifest.json")
    check("dye-three-variants", len(manifest["variants"]) == 3 and manifest["dye_gbid"] == -234196792)
    for tag in ("A", "B", "C"):
        doc = load(tag + "-lists.json")
        check("dye-" + tag + "-rows-zero", eligible_item_rows(doc) == 0, eligible_item_rows(doc))
        page = load(tag + "-dye-page-ui.json")
        check("dye-" + tag + "-page", "染料" in texts(page))
    check("dye-historical-pages-mainhand", all(
        "主手" in texts(load(tag + "-dye-page-ui.json")) for tag in ("A", "B", "C")))
    inv = load("A-inventory-ui.json")
    check("dye-bag-unchanged", "物品栏 {c_white}18/60{/c}" in texts(inv))
    save = load("save-after.json")
    check("dye-save-clean", len(save["heroes"][0]["items"]) == 23)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "checks": 10, "evidence_sha256": evidence,
               "note": "quality 4/0/1 clones absent after load; main-hand eligible item list rows=0, bag 18/60, save 23 items; built-in armor colors require no dye items"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("10 dye injection checks passed")


if __name__ == "__main__":
    main()
