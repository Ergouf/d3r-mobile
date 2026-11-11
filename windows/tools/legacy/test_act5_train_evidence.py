"""Verify the Act 5 blacksmith training on the 0054 build.

The 训练 page quotes 10000 gold for the next rank; the footer 训练 legend pays it,
the recipes jump from level 30 to 35 and the save shows crafter 3 -> 4.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act5-train-0054"
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
    page = load("train-page-ui.json")
    done = load("train-done-ui.json")
    save = load("save-after.json")
    for tag, doc in (("page", page), ("done", done)):
        check("train-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    page_texts = texts(page)
    check("train-page-legend", any(t.startswith("{icon:button1") and "训练" in t for t in page_texts))
    check("train-page-cost", "10000 {icon:gold}" in page_texts and "729955 {icon:gold}" in page_texts)
    check("train-page-requires", any("需要等级" in t for t in page_texts))
    done_texts = texts(done)
    check("train-charged", "-10000 {icon:gold}" in done_texts and "719955 {icon:gold}" in done_texts)
    check("train-next-cost", "15000 {icon:gold}" in done_texts and "需要等级{c_white}35{/c}" in done_texts)
    part = save["partitions"][0]
    check("train-save-crafter", part["crafter_levels"] == [4, 9, 10, 0])
    check("train-save-gold", part["currencies"]["0"] == 719955)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 9, "evidence_sha256": evidence,
               "note": "10000 gold spent, recipes 30 -> 35, crafter levels [3,9,10,0] -> [4,9,10,0]"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("9 Act 5 training checks passed")


if __name__ == "__main__":
    main()
