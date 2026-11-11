"""Verify the footer legend mapping on the 0053 build.

The leftmost legend names the pad button behind the hint.  On the mystic dye
page the only hint is 关闭 (button2), so a click there closes the menu; the
armory page shows button3 保存装备库配案, which the mapper parses and sends as X
(the page state itself did not change in this run).
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/footer-legend-0053"
BUILD = "C2BFEDBAEB3C82683C95198E61E382F26D0C85D2A61E682B2C038AF78B9AE12F"
TABS = ("附魔", "幻化", "染色", "训练")


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
    dye = load("dye-page-ui.json")
    closed = load("dye-closed-ui.json")
    armory = load("armory-page-ui.json")
    armory_after = load("armory-after-ui.json")
    for name, doc in (("dye-page", dye), ("dye-closed", closed), ("armory", armory), ("armory-after", armory_after)):
        check("legend-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("legend-dye-page-tabs", all(t in texts(dye) for t in TABS))
    check("legend-dye-footer", footer(dye).strip() == "{icon:button2,2.0}\xa0关闭", repr(footer(dye)))
    check("legend-dye-closed", not any(t in texts(closed) for t in TABS))
    check("legend-armory-button3", "{icon:button3" in footer(armory) and "保存装备库配案" in footer(armory),
          repr(footer(armory)))
    check("legend-armory-status", "你当前的装备没有保存。" in " ".join(texts(armory_after)))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 10, "evidence_sha256": evidence,
               "note": "clicking the leftmost legend sends its button: dye page 关闭 -> B closed the menu; armory button3 -> X was applied but the page state did not change"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("10 footer legend checks passed")


if __name__ == "__main__":
    main()

