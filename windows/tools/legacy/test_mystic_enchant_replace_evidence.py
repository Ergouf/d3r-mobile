"""Verify the mystic enchant cancel and the replacement of an existing affix.

The 0047/0048 footer mapping already reached the affix list; this run closes the
remaining gaps: B cancels the list with no charge, and picking an affix on an
item that already has an enchant replaces it, then 附魔 confirms and 接受 ends.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/mystic-enchant-replace-0051"
BUILD = "51402FEB85E593A98D2C21FFE6EFF584585EC632FF3C289DF8C1C317768B1E9F"
ITEM_GBID = -635269580


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [x["text"] for x in d["items"] if x.get("text") and x["visible"]]


def footer(d):
    for t in texts(d):
        if t.startswith("{icon:button"):
            return t
    raise AssertionError("no footer legend")


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    docs = {n: load(n + ".json") for n in ("list-ui", "cancel-ui", "picked-ui", "applied-ui", "accepted-ui")}
    for name, doc in docs.items():
        check("enchant-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("enchant-list-opens", "替换之前附魔的属性：" in " ".join(texts(docs["list-ui"])) and
          "查看可替换的属性" in footer(docs["list-ui"]))
    check("enchant-cancel-footer", "选择" in footer(docs["cancel-ui"]) and "对比" in footer(docs["cancel-ui"]))
    check("enchant-cancel-no-charge", "865474 {icon:gold}" in " ".join(texts(docs["cancel-ui"])) and
          "-14446 {icon:gold}" not in " ".join(texts(docs["cancel-ui"])))
    check("enchant-affix-picked", "附魔" in footer(docs["picked-ui"]) and "取消" in footer(docs["picked-ui"]) and
          "-14446 {icon:gold}" in " ".join(texts(docs["picked-ui"])))
    check("enchant-applied-ui", "完成" in " ".join(texts(docs["applied-ui"])) and
          "851028 {icon:gold}" in " ".join(texts(docs["applied-ui"])))
    check("enchant-accepted-ui", "选择" in footer(docs["accepted-ui"]) and
          "851028 {icon:gold}" in " ".join(texts(docs["accepted-ui"])))

    before, after = load("save-before.json"), load("save-after.json")
    part_b, part_a = before["partitions"][0], after["partitions"][0]
    check("enchant-save-gold", part_b["currencies"]["0"] == 865474 and part_a["currencies"]["0"] == 851028)
    check("enchant-save-materials", part_b["currencies"]["4"] == 897 and part_a["currencies"]["4"] == 895 and
          part_b["currencies"]["5"] == 950 and part_a["currencies"]["5"] == 948)
    item_b = [i for i in before["heroes"][0]["items"] if i["gbid"] == ITEM_GBID][0]
    item_a = [i for i in after["heroes"][0]["items"] if i["gbid"] == ITEM_GBID][0]
    check("enchant-save-count", item_b["enchanted_affix_count"] == 3 and item_a["enchanted_affix_count"] == 4)
    check("enchant-save-affix", item_b["enchanted_affix_new"] == 49371923 and item_a["enchanted_affix_new"] == 49371923)
    check("enchant-items-stable", len(before["heroes"][0]["items"]) == len(after["heroes"][0]["items"]) == 21)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 16, "evidence_sha256": evidence,
               "note": "B cancels the affix list at 865474; picking +6-8 holy damage replaces the existing affix for 14446 gold (count 3->4)"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("16 enchant replace checks passed")


if __name__ == "__main__":
    main()


