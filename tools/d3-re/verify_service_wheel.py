"""Serial SDL checks of a currently open service's inventory/crafting wheel.

Records modes without a visible supported wheel as uncovered. Checks native
icon/cursor state, mapped category and actual page content together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from version import EXE, assert_installed

HERE = Path(__file__).resolve().parent
TITLES = dict(zip(
    ['sword','crossbow','dagger','wand','mace','offhand','mighty','staff','axe','fist','bow','flail','scythe',
     'fingerleft','fingerright','neck','hands','shoulder','torso','head','waist','legs','feet','bracers','bag'],
    ['剑','弩','匕首','魔杖','钉锤','副手','重武器','法杖','斧','拳套武器','弓','连枷','镰刀',
     '戒指','戒指','颈部','手套','肩部','胸部','头部','腰部','腿部','脚部','手腕','背包']))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--group", type=int, choices=(2, 5, 6, 7), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "result.json").exists():
        raise RuntimeError("use a new evidence directory")
    build = assert_installed()

    def identity():
        command = (f"$p=Get-Process -Id {args.pid} -ErrorAction Stop; "
                   "@{path=$p.Path;start=$p.StartTime.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress")
        return json.loads(subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True))

    process = identity()
    if process["path"].lower() != str(EXE).lower():
        raise RuntimeError("unexpected executable path")
    report = {"process": {"pid": args.pid, **process}, "build": build,
              "scope": __doc__, "checks": [], "modes": []}

    def save():
        (args.out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    def run(script, *values):
        if identity() != process:
            raise RuntimeError("process identity changed")
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
            r = subprocess.run([sys.executable, str(HERE / script), "--pid", str(args.pid),
                                *map(str, values)], stdout=log, stderr=subprocess.STDOUT, timeout=25)
            log.seek(0)
            output = log.read()
        if r.returncode:
            raise RuntimeError(output[-1800:])

    def snap(name):
        path = args.out / (name + ".json")
        run("probe_wheel_state.py", "--out", path)
        return json.loads(path.read_text("utf-8"))

    def check(name, passed, **evidence):
        report["checks"].append({"name": name, "passed": bool(passed), **evidence})
        save()
        print(("PASS " if passed else "FAIL ") + name + " " + json.dumps(evidence, ensure_ascii=False), flush=True)
        if not passed:
            raise RuntimeError(name)

    def text(state):
        return [c["text"] for c in state["content"] if c.get("visible") and c.get("text")]

    def gold(state):
        return sorted(t["text"] for t in state["texts"] if "{icon:gold}" in t["text"])

    def highlight(state, key):
        native = state["service"]["nativeWheel"]
        entry = next((e for e in native["entries"] if e["key"] == key), None)
        if not entry or native.get("selectedKey") != key or not native["cursor"]["visible"]:
            return False
        expected = (math.pi - entry["angle"]) % math.tau
        delta = (native["cursor"]["angle"] - expected + math.pi) % math.tau - math.pi
        states = [e for e in native["entries"] if e.get("highlight") and e["highlight"]["state"] is not None]
        icons_ok = len(states) == len(native["entries"]) and all((e["highlight"]["state"] == 1) == (e["key"] == key) for e in states)
        return native["enabled"] == native["rotates"] == 1 and abs(delta) < .0001 and icons_ok

    initial = snap("initial")
    if initial["groupIndex"] != args.group or not initial["service"]:
        raise RuntimeError("open the requested service first")
    tabs = initial["navigationEntries"]
    lefts = [90, 246, 402, 558, 714] if args.group == 5 else [126, 303, 505, 682]
    for tab in tabs:
        index = tab["index"]
        before = snap(f"mode-{index}-before")
        run("probe_pointer_click.py", "--x", lefts[index] + 160 + 78, "--y", 51)
        time.sleep(.25)
        start = snap(f"mode-{index}-start")
        if not tab["enabled"]:
            check(f"mode-{index}-disabled", start["pageSelected"] == before["pageSelected"])
            report["modes"].append({"page": index, "coverage": "disabled-tab"})
            continue
        check(f"mode-{index}-page", start["groupIndex"] == args.group and start["pageSelected"] == index,
              content=text(start))
        craft = args.group == 5 and index < 2
        expected_count = (13 if index == 0 else 12) if craft else 14
        entries = start["service"]["nativeWheel"]["entries"] if craft else start["equipment"]["entries"]
        visible = [e for e in entries if e.get("visible")]
        if not visible:
            report["modes"].append({"page": index, "mode": start["service"]["mode"],
                                    "coverage": "no-visible-supported-wheel", "content": text(start)})
            save()
            continue
        check(f"mode-{index}-wheel-shape", len(visible) == expected_count and start["service"]["active"] == 1 and
              start["equipment"]["active"] == 0)
        serial = start["runtime"]["serial"]
        previous = start
        for entry in visible:
            r = entry["rect"]
            x, y = (r[0] + r[2]) / 2 + 160, (r[1] + r[3]) / 2
            run("probe_pointer_move.py", "--engine", "--x", x, "--y", y)
            time.sleep(.2)
            after = snap(f"mode-{index}-hover-{entry['index']}")
            content = text(after)
            category = entry["category"] if craft else entry["index"]
            changed = (content == [TITLES[entry["name"]]]) if craft else (
                previous["service"]["selected"] == category or content != text(previous))
            check(f"mode-{index}-hover-{entry['name']}", after["groupIndex"] == args.group and
                  after["pageSelected"] == index and after["service"]["selected"] == category and
                  highlight(after, entry["key"]) and bool(content) and changed and
                  after["runtime"]["serial"] == serial and
                  after["equipment"]["selected"] == start["equipment"]["selected"] and
                  gold(after) == gold(start), category=category, content=content,
                  expected_content=[TITLES[entry["name"]]] if craft else None,
                  cursor=after["service"]["nativeWheel"]["cursor"])
            previous = after
        run("probe_pointer_move.py", "--engine", "--x", 1100, "--y", 600)
        run("probe_pointer_move.py", "--engine", "--x", lefts[index] + 238, "--y", 51)
        outside = snap(f"mode-{index}-outside")
        check(f"mode-{index}-outside", outside["pageSelected"] == index and
              outside["service"]["selected"] == previous["service"]["selected"] and text(outside) == text(previous) and
              outside["runtime"]["serial"] == serial)
        entry = visible[0]
        r = entry["rect"]
        run("probe_pointer_click.py", "--x", (r[0] + r[2]) / 2 + 160, "--y", (r[1] + r[3]) / 2)
        time.sleep(.2)
        clicked = snap(f"mode-{index}-click")
        check(f"mode-{index}-click", clicked["pageSelected"] == index and
              clicked["service"]["selected"] == (entry["category"] if craft else entry["index"]) and highlight(clicked, entry["key"]) and
              bool(text(clicked)) and gold(clicked) == gold(start), content=text(clicked))
        report["modes"].append({"page": index, "mode": start["service"]["mode"],
                                "coverage": f"{expected_count}-native-highlight-and-content"})
        save()
    report["all_checks_passed"] = all(c["passed"] for c in report["checks"])
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
