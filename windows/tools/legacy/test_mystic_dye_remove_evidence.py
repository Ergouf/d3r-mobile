"""Verify the L3 footer hint removes a dye through the native pad path.

The dye page shows `选择 / 对比 / 返回 / 移除染色` where the last hint carries
`{icon:l3}`.  The 0055 footer handler maps the clicked hint cell to that icon
name, so a click in the rightmost cell presses the console's L3 button and the
game clears the dye; the cold save then differs only in the dye fields.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/dye-remove-0055"
PREV = ROOT / "out/windows/kbm/session/dye-business-0054"
BUILD = "34E226ACF6C27618B814BBB1EA19432E3D356EA3923D260A263836B3875B1FAC"


def load(p):
    return json.loads(Path(p).read_text("utf-8"))


def texts(state):
    return [t["text"] for t in state["texts"]]


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    checks = 0
    before = load(EVID / "wheel-selected.json")
    after = load(EVID / "wheel-after-l3.json")
    click = load(EVID / "click-l3.json")
    save_before = load(PREV / "save-final-cold.json")
    save_after = load(EVID / "save-after-remove.json")
    log = (EVID / "log-delta.txt").read_text("utf-8")

    for name, doc in (("wheel-before", before), ("wheel-after", after), ("click", click)):
        check("same-build-" + name, doc["build"]["exe_sha256"] == BUILD, doc["build"]["exe_sha256"])
        checks += 1

    fb = next(t for t in texts(before) if "{icon:button1" in t)
    fa = next(t for t in texts(after) if "{icon:button1" in t)
    check("footer-before-hints", fb.count("{icon:") == 4 and "{icon:l3,2.0}" in fb and "移除染色" in fb, fb)
    check("footer-hint-order", [fb.index(x) for x in ("选择", "对比", "返回", "移除染色")]
          == sorted(fb.index(x) for x in ("选择", "对比", "返回", "移除染色")))
    check("footer-after-hints", "{icon:l3" not in fa and "移除染色" not in fa and fa.count("{icon:") == 3, fa)
    checks += 3

    check("item-before-shows-dye", any("当前外观" in t for t in texts(before)))
    check("item-after-no-dye", any(t.strip() == "没有染色" for t in texts(after)))
    checks += 2

    check("click-in-fourth-cell", click["enginePixel"][0] >= 960, click["enginePixel"])
    check("log-l3-queued", "footer legend 33 l3 -> queued" in log, log)
    check("log-l3-bit", "bits 04000" in log)
    checks += 3

    def chest(doc):
        return next(i for i in doc["heroes"][0]["items"] if i["slot"] == 304)
    cb, ca = chest(save_before), chest(save_after)
    check("save-dye-cleared", cb["dye"] == 10 and ca["dye"] == 0, (cb["dye"], ca["dye"]))
    check("save-item-identity", cb["gbid"] == ca["gbid"])
    check("save-gold-unchanged", save_before["partitions"][0]["currencies"]["0"]
          == save_after["partitions"][0]["currencies"]["0"] == 717043)
    check("save-item-count", len(save_before["heroes"][0]["items"])
          == len(save_after["heroes"][0]["items"]) == 23)
    changed = sorted(k for k in set(cb) | set(ca) if cb.get(k) != ca.get(k))
    check("save-only-dye-fields", set(changed) <= {"dye", "generator_sha256"}, changed)
    checks += 5

    evidence = {}
    for p in sorted(EVID.iterdir()):
        if p.is_file() and p.suffix in (".json", ".txt"):
            evidence[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (EVID / "summary.json").write_text(json.dumps({
        "scope": __doc__, "build": BUILD, "checks": checks, "evidence_sha256": evidence,
        "result": "L3 footer hint click removed the chest dye 10->0 with no gold change; "
                  "only dye/generator fields moved in the cold save",
        "boundary": "re-dyeing after removal was not repeated; the 0055 handler is live-verified "
                    "for button1..4 (unchanged paths) and l3",
    }, ensure_ascii=False, indent=2), "utf-8")
    print(f"{checks} dye-removal checks passed")


if __name__ == "__main__":
    raise SystemExit(main())
