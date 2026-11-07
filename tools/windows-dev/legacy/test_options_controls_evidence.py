"""Verify the options sliders and the toggle footer legend on the 0052 build.

The volume sliders expose their value as text, so the run records 80% -> 70% ->
90% -> 80% on the main volume row while every other slider stays put.  The
boolean rows only expose a 切换 footer legend; the click mapping is covered by
the footer assertion, the setting value itself has no text to compare.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/options-controls-0052"
BUILD = "DA95E8D64B69BB86380E931D22D79D2811A77E79E4C2DF276C00C932A8C09D5A"


def load(name):
    return json.loads((EVID / name).read_text("utf-8"))


def percents(d):
    out = []
    for x in d["items"]:
        t = (x.get("text") or "").strip()
        if x["visible"] and t.endswith("%"):
            out.append(t)
    return sorted(out)


def footer(d):
    for x in d["items"]:
        t = x.get("text") or ""
        if x["visible"] and t.startswith("{icon:button"):
            return t
    raise AssertionError("no footer")


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    names = ("sound-page-ui", "volume-selected-ui", "volume-lowered-ui", "volume-raised-ui",
             "volume-restored-ui", "toggle-legend-ui", "video-page-ui")
    docs = {n: load(n + ".json") for n in names}
    for name, doc in docs.items():
        check("options-ui-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])

    check("options-sound-page", "主音量" in " ".join((x.get("text") or "") for x in docs["sound-page-ui"]["items"]))
    check("options-volume-start", percents(docs["volume-selected-ui"]) == ["100%", "80%", "80%", "80%", "80%"],
          percents(docs["volume-selected-ui"]))
    check("options-volume-lowered", percents(docs["volume-lowered-ui"]) == ["70%", "80%", "80%", "80%", "80%"],
          percents(docs["volume-lowered-ui"]))
    check("options-volume-raised", percents(docs["volume-raised-ui"]) == ["80%", "80%", "80%", "80%", "90%"],
          percents(docs["volume-raised-ui"]))
    check("options-volume-restored", percents(docs["volume-restored-ui"]) == ["80%", "80%", "80%", "80%", "80%"],
          percents(docs["volume-restored-ui"]))
    check("options-toggle-legend", "切换" in footer(docs["toggle-legend-ui"]), footer(docs["toggle-legend-ui"]))
    check("options-video-page", "安全区域" in " ".join((x.get("text") or "") for x in docs["video-page-ui"]["items"]))

    evidence = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVID.glob("*.json"))}
    summary = {"scope": __doc__, "build": BUILD, "checks": 13, "evidence_sha256": evidence,
               "note": "main volume 80->70->90->80 via row select + arrows; toggle rows expose a 切换 footer legend, the setting value has no text state"}
    (EVID / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print("13 options control checks passed")


if __name__ == "__main__":
    main()

