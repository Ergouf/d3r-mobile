"""Verify the Act 5 town menus on the 0053 build.

The mystic workbench there used to swallow the click; with the 0050 retry the
click walks to the bench and Space opens group 7, and the tab strip switches to
the transmog page.  The blacksmith opens with its weapon/armor/salvage tabs.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act5-town-0053"
BUILD = "C2BFEDBAEB3C82683C95198E61E382F26D0C85D2A61E682B2C038AF78B9AE12F"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def page_header(d):
    for x in d["items"]:
        if x["visible"] and x["rect"][1] == -27:
            return (x.get("text") or "").strip()
    raise AssertionError("no page header")


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
    mystic = load("mystic-menu-ui.json")
    transmog = load("mystic-transmog-ui.json")
    smith = load("smith-menu-ui.json")
    jeweler = load("jeweler-menu-ui.json")
    for name, doc in (("mystic", mystic), ("mystic-transmog", transmog), ("smith", smith), ("jeweler", jeweler)):
        check("act5-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    tabs = ("附魔", "幻化", "染色", "训练")
    check("act5-mystic-tabs", all(t in texts(mystic) for t in tabs))
    check("act5-mystic-page0", page_header(mystic) == "附魔", page_header(mystic))
    check("act5-mystic-page1", page_header(transmog) == "幻化", page_header(transmog))
    check("act5-mystic-footer", "选择" in footer(mystic) and "关闭" in footer(mystic))

    check("act5-smith-tabs", all(t in texts(smith) for t in ("武器", "护甲", "分解")))
    check("act5-smith-name", "黑德里格·埃蒙" in " ".join(texts(smith)))
    check("act5-smith-footer", "选择" in footer(smith) and "更换筛选" in footer(smith))
    check("act5-jeweler-tabs", all(t in texts(jeweler) for t in ("合成", "镶孔", "移除", "训练")))
    check("act5-jeweler-name", "沈老贪" in " ".join(texts(jeweler)))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 12, "evidence_sha256": evidence,
               "note": "Act 5 mystic opens through the workbench retry and switches 附魔->幻化; the blacksmith shows 武器/护甲/分解"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("12 Act 5 menu checks passed")


if __name__ == "__main__":
    main()

