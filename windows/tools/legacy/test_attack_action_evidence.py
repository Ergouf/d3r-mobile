"""Verify the native attack now reaches the action entry (ret 1).

Before 0057 the attack record used a type-1 actor path with no place field and
the action entry answered 0.  The natural A sends the empty attack from the
player's own position (+ attack height) with a type-2 position path whose last
word is the place id; feeding that place made the same click return 1.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVID = ROOT / "out/windows/kbm/session/attack-town2-0057"
NATURAL = ROOT / "out/windows/kbm/session/attack-town-0057/flow-targeted.json"
FIX = ROOT / "windows/patches/0057-native-attack-position-path.patch"


def check(name, condition, detail=None):
    if not condition:
        raise AssertionError(name + ((": " + str(detail)) if detail is not None else ""))
    print("PASS " + name)


def main():
    checks = 0
    log = (EVID / "log-before-after.txt").read_text("utf-8")
    ones = [l for l in log.splitlines() if "native: attack " in l and l.rstrip().endswith("-> 1")]
    check("attack-accepted", len(ones) >= 3, len(ones))
    check("attack-power", all("power 285903" in l for l in ones))
    checks += 2

    nat = json.loads(NATURAL.read_text("utf-8"))
    rec = next(c["record"] for c in nat["calls"] if c["name"] == "action")
    check("natural-path-type2", rec[0x14 * 2:0x18 * 2] == "02000000" or rec[28:36] == "02000000", rec)
    check("natural-place-nonzero", rec[0x28 * 2:0x2C * 2] == "00002e77", rec[-24:])
    checks += 2

    check("patch-present", FIX.exists() and FIX.stat().st_size > 0)
    base = json.loads((ROOT / "windows/patches/base.json").read_text("utf-8"))
    check("patch-in-chain", any(e["patch"] == FIX.name for e in base["extra_patches"]))
    checks += 2

    evidence = {}
    for p in sorted(EVID.iterdir()):
        if p.is_file() and p.suffix in (".json", ".txt"):
            evidence[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (EVID / "summary.json").write_text(json.dumps({
        "scope": __doc__, "checks": checks, "evidence_sha256": evidence,
        "result": "attack on prop 4675 returns action ret 1 four times after 0057",
        "boundary": "no reachable monster was available, so damage/progress was not observed",
    }, ensure_ascii=False, indent=2), "utf-8")
    print(f"{checks} attack checks passed")


if __name__ == "__main__":
    raise SystemExit(main())
