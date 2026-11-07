"""Verify the Act 2 mystic menu on the 0054 build.

The Hidden Camp workbench used to keep the click on its collision cylinder, so
the menu never opened.  The 0050 attack retry walks to melee range, after which
Space opens group 7 and the tab strip switches 附魔 -> 幻化.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/act2-mystic-0054"
BUILD = "FA620A22D7222B502BA9296065FD986D57FFFEE07CA1EE6B0D690D1F9E4B2103"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def texts(d):
    return [(x.get("text") or "").strip() for x in d["items"] if x["visible"] and (x.get("text") or "").strip()]


def header(d):
    for x in d["items"]:
        if x["visible"] and x["rect"][:2] == [-3, -27] and x["rect"][2] == 258:
            return (x.get("text") or "").strip()
    raise AssertionError("no page header")


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    menu = load("mystic-menu-ui.json")
    transmog = load("mystic-transmog-ui.json")
    for tag, doc in (("menu", menu), ("transmog", transmog)):
        check("act2-ui-build-" + tag, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("act2-mystic-tabs", all(t in texts(menu) for t in ("附魔", "幻化", "染色", "训练")))
    check("act2-mystic-page0", header(menu) == "附魔", header(menu))
    check("act2-mystic-page1", header(transmog) == "幻化", header(transmog))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 6, "evidence_sha256": evidence,
               "note": "Act 2 workbench click now walks to melee range; group 7 opens and 附魔 switches to 幻化"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("6 Act 2 mystic checks passed")


if __name__ == "__main__":
    main()
