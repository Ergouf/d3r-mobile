"""Correlate real mouse test timestamps with independent UI state observations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SLOTS = [0, 1, 2, 4, 5]


def page_index(state: dict) -> int | None:
    visible = [i for i, p in enumerate(state["pages"]) if p["visible"]]
    if len(visible) != 1:
        return None
    index = visible[0]
    return index if state["selected"] == SLOTS[index] else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actions", type=Path, required=True)
    ap.add_argument("--watch", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    actions = json.loads(args.actions.read_text(encoding="utf-8-sig"))
    watch = json.loads(args.watch.read_text(encoding="utf-8-sig"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    if watch["errors"] or watch["build"] != baseline["build"] or watch["pid"] != baseline["pid"]:
        raise SystemExit("observer errors, build mismatch or PID mismatch")
    states = [r for r in watch["records"] if r["kind"] == "state"]
    selectors = [r for r in watch["records"] if r["kind"] == "selector"]
    pulses = [r for r in watch["records"] if r["kind"] == "native_action"]
    cases = []
    for source in range(5):
        for target in range(5):
            recorded = [r for r in actions if r.get("source") == source and r.get("target") == target]
            if len(recorded) != 1:
                raise SystemExit(f"expected exactly one action for {source}->{target}")
            action = recorded[0]
            if action.get("status") == "SKIP":
                if source != 3 or baseline["entries"][4]["enabled"] != 0:
                    raise SystemExit("unjustified skipped source")
                cases.append({"source": source, "target": target, "status": "SKIP",
                              "reason": "party native slot 4 disabled; source cannot be entered"})
                continue
            start, end = action["actionStartMs"], action["actionEndMs"]
            before = next((r for r in reversed(states) if r["t"] <= start), None)
            after = next((r for r in states if r["t"] >= end), None)
            if not before or not after or start - before["t"] > 1500 or after["t"] - end > 1500:
                raise SystemExit(f"no nearby before/after observation for {source}->{target}")
            expected = source if target == 3 else target
            calls = [r for r in selectors if start <= r["t"] <= end]
            expected_calls = int(target != 3 and source != target)
            actual_before, actual_after = page_index(before["state"]), page_index(after["state"])
            checks = {
                "source_page": actual_before == source,
                "destination_page": actual_after == expected,
                "visual_result": action.get("success") is True and action.get("actual") == expected,
                "selector_count": len(calls) == expected_calls,
                "selector_arguments": all(r["args"] == ["0", str(SLOTS[target]), "0", "0"] for r in calls),
                "no_action_pulse": not any(start <= r["t"] <= end for r in pulses),
            }
            cases.append({"source": source, "target": target,
                          "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
                          "before": before, "after": after, "selectors": calls,
                          "action": action})
    negatives = []
    for action in actions:
        if "case" not in action:
            continue
        start, end = action.get("actionStartMs"), action.get("actionEndMs")
        if start is None or end is None:
            negatives.append({"action": action, "status": "LIMITED"})
            continue
        calls = [r for r in selectors if start <= r["t"] <= end]
        negative_pulses = [r for r in pulses if start <= r["t"] <= end]
        # Esc/B and BackSpace/Minus deliberately close pages. Neither is L/R/A.
        no_lra = all(not (int(r["pad"], 16) & 0xC1) for r in negative_pulses)
        status = "PASS" if action.get("success") is True else "LIMITED"
        if calls or not no_lra or action.get("success") is False:
            status = "FAIL"
        negatives.append({"action": action, "status": status, "selectors": calls,
                          "no_L_R_A_pulse": no_lra, "pulses": negative_pulses})
    result = {"pid": watch["pid"], "build": watch["build"], "cases": cases,
              "negative_cases": negatives, "observer_errors": watch["errors"],
              "pass": sum(c["status"] == "PASS" for c in cases),
              "skip": sum(c["status"] == "SKIP" for c in cases),
              "fail": sum(c["status"] == "FAIL" for c in cases + negatives)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("PASS", result["pass"], "SKIP", result["skip"], "FAIL", result["fail"])
    print("negative", [(r["action"]["case"], r["status"]) for r in negatives])
    if result["fail"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
