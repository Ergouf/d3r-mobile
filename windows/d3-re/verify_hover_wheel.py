"""Serial SDL-motion matrix with wheel-controller AND page-content evidence.

Start in the inventory page. This selects categories, not items or skills.
Uses only SDL events and read-only probes; all Frida sessions are serial.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from version import EXE, assert_installed

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "out/windows/kbm/session/hover-live")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    build = assert_installed()
    # Capture path, creation time and SHA together; refuse a reused PID per call.
    def identity() -> dict:
        command = (f"$p=Get-Process -Id {args.pid} -ErrorAction Stop; "
                   "@{path=$p.Path;start=$p.StartTime.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress")
        return json.loads(subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True))
    process = identity()
    if process["path"].lower() != str(EXE).lower():
        raise RuntimeError("unexpected process executable")
    report = {"build": build, "process": {"pid": args.pid, **process}, "scope": __doc__, "checks": []}

    def run(script: str, *values) -> None:
        if identity() != process:
            raise RuntimeError("process identity changed")
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log:
            done = subprocess.run([sys.executable, str(HERE / script), "--pid", str(args.pid),
                                   *map(str, values)], stdout=log, stderr=subprocess.STDOUT, timeout=25)
            log.seek(0)
            output = log.read()
        if done.returncode:
            raise RuntimeError(output[-2000:])

    def snapshot(name: str) -> dict:
        out = args.out / (name + ".json")
        run("probe_wheel_state.py", "--out", out)
        return json.loads(out.read_text("utf-8"))

    def motion(x: float, y: float) -> None:
        run("probe_pointer_move.py", "--engine", "--x", x, "--y", y)
        time.sleep(.2)

    def title(state: dict, page: int) -> list:
        return [{"name": c["name"].split(".")[-1], "text": c["text"]}
                for c in state["content"] if c["visible"] and c["text"] and
                ((page == 0) == ("consoleinventoryring_main" in c["name"]))]

    def check(name: str, passed: bool, **evidence) -> None:
        report["checks"].append({"name": name, "passed": bool(passed), **evidence})
        print(("PASS " if passed else "FAIL ") + name + " " +
              json.dumps(evidence, ensure_ascii=False), flush=True)
        (args.out / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
        if not passed:
            raise RuntimeError(name)

    def highlighted(state: dict, wheel: str, key: str) -> bool:
        native = state[wheel]["nativeWheel"]
        entry = next((e for e in native["entries"] if e["key"] == key), None)
        if not entry or not native["cursor"]["visible"] or native["selectedKey"] != key:
            return False
        expected = (math.pi - entry["angle"]) % math.tau
        delta = (native["cursor"]["angle"] - expected + math.pi) % math.tau - math.pi
        states = [e for e in native["entries"] if e.get("highlight") and e["highlight"]["state"] is not None]
        icons_ok = bool(states) and all((e["highlight"]["state"] == 1) == (e["key"] == key) for e in states)
        return native["enabled"] == 1 and native["rotates"] == 1 and abs(delta) < .0001 and icons_ok

    before = snapshot("equipment-before")
    if before["groupIndex"] != 0 or before["pageSelected"] != 0:
        raise RuntimeError("open inventory first")
    serial = before["runtime"]["serial"]
    for page, wheel in ((0, "equipment"), (1, "skill")):
        if page:
            run("probe_pointer_click.py", "--x", 484, "--y", 51)
            time.sleep(.4)
        start = snapshot(wheel + "-initial")
        serial = start["runtime"]["serial"]
        check(wheel + "-page", start["groupIndex"] == 0 and start["pageSelected"] == page)
        points = []
        previous = start
        for entry in start[wheel]["entries"]:
            if not entry.get("visible"):
                continue
            r = entry["rect"]
            x, y = (r[0] + r[2]) / 2 + 160, (r[1] + r[3]) / 2
            points.append((x, y))
            motion(x, y)
            after = snapshot(wheel + "-" + str(entry["index"]))
            content = title(after, page)
            changed = previous[wheel]["selected"] == entry["index"] or content != title(previous, page)
            check(wheel + "-hover-" + str(entry["index"]),
                  after[wheel]["selected"] == entry["index"] and bool(content) and
                  changed and after["pageSelected"] == page and after["runtime"]["serial"] == serial and
                  highlighted(after, wheel, entry["key"]),
                  entry=entry["name"], content=content, page_content_checked=changed,
                  native_highlight=after[wheel]["nativeWheel"]["cursor"])
            previous = after
        last = after
        x, y = points[-1]
        for dx in (1, -1, 0):
            motion(x + dx, y)
        after = snapshot(wheel + "-repeat")
        check(wheel + "-repeat", after[wheel]["selected"] == last[wheel]["selected"] and title(after,page) == title(last,page))
        motion(1100, 600)
        motion(484, 51)  # Top page tab: hovering must not click it.
        after = snapshot(wheel + "-outside")
        check(wheel + "-outside-and-page-tab", after[wheel]["selected"] == last[wheel]["selected"] and
              after["pageSelected"] == page and after["runtime"]["serial"] == serial)

    run("probe_sdl_key.py", "--key", "esc")
    time.sleep(.3)
    world = snapshot("world-before")
    motion(350, 250)
    after = snapshot("world-after")
    check("world-motion-no-click", not after["runtime"]["blocked"] and after["runtime"]["serial"] == world["runtime"]["serial"])
    run("probe_sdl_key.py", "--key", "backspace")
    time.sleep(.3)
    pause = snapshot("pause-before")
    motion(384, 102)
    after = snapshot("pause-after")
    check("pause-isolation", pause["groupIndex"] == after["groupIndex"] == 21 and
          pause["pageSelected"] == after["pageSelected"] and
          pause["equipment"]["selected"] == after["equipment"]["selected"] and
          pause["skill"]["selected"] == after["skill"]["selected"])
    run("probe_sdl_key.py", "--key", "esc")
    run("probe_sdl_key.py", "--key", "i")
    time.sleep(.3)
    report["final"] = snapshot("final-inventory")
    def resources(state: dict) -> list[str]:
        return sorted(t["text"] for t in state["texts"] if
                      re.match(r"^\d+ .*\{icon:gold\}", t["text"]) or
                      re.search(r"物品栏 .*\d+/\d+", t["text"]))
    check("resources-and-item-count-unchanged", resources(report["final"]) == resources(before),
          before=resources(before), after=resources(report["final"]))
    report["all_passed"] = all(c["passed"] for c in report["checks"])
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.out / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
