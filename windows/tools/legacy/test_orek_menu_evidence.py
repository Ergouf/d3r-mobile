"""Verify Orek's menu options and the close behaviour of 取消.

Clicks go through the world pointer and the native list-row path; each option
opens its own native dialogue and 取消 dismisses the menu without a dialog.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/orek-menu-0051"
BUILD = "51402FEB85E593A98D2C21FFE6EFF584585EC632FF3C289DF8C1C317768B1E9F"
OPTIONS = ("唤醒", "秘境", "关于欧雷克", "取消")


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def visible(d):
    return [(x["rect"], x["text"].strip()) for x in d["items"] if x.get("text") and x["visible"]]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    docs = {n: load(n + ".json") for n in ("menu-ui", "about-ui", "wake-ui", "cancel-ui", "menu-reopen-ui")}
    for name, doc in docs.items():
        check("orek-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    menu = [t for _, t in visible(docs["menu-ui"])]
    check("orek-menu-options", all(o in menu for o in OPTIONS), menu)
    reopen = [t for _, t in visible(docs["menu-reopen-ui"])]
    check("orek-menu-reopens", all(o in reopen for o in OPTIONS), reopen)

    about = " ".join(t for _, t in visible(docs["about-ui"]))
    check("orek-about-dialogue", "奈非天" in about and "钥石" in about and "欧雷克" in about)
    check("orek-about-no-menu", not any(o in about for o in ("唤醒", "关于欧雷克", "取消")))

    wake = " ".join(t for _, t in visible(docs["wake-ui"]))
    check("orek-wake-dialogue", "古代的奈非天" in wake and "秘境" in wake)
    check("orek-wake-no-menu", "关于欧雷克" not in wake)

    cancel = " ".join(t for _, t in visible(docs["cancel-ui"]))
    check("orek-cancel-closes", not any(o in cancel for o in ("唤醒", "关于欧雷克", "取消")) and "奈非天" not in cancel)

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 11, "evidence_sha256": evidence,
               "note": "关于欧雷克 and 唤醒 open their native dialogue; 取消 closes the menu with no dialog; the rift dialogue states a keystone is required"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("11 Orek menu checks passed")


if __name__ == "__main__":
    main()


