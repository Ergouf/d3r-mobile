"""Verify a queued SDL ground click reaches its native world destination.

Run while player 0 is idle in a world with a clear, nearby floor point. No
foreground activation, real cursor, controller writes, or movement calls.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import time
from pathlib import Path

import frida

import probe_pointer_click
import probe_world_move
from version import assert_installed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--x", required=True, type=float)
    ap.add_argument("--y", required=True, type=float)
    ap.add_argument("--seconds", default=3.0, type=float)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if not (0 <= args.x < 1280 and 0 <= args.y < 720 and 1 <= args.seconds <= 30):
        ap.error("pixel must be in 1280x720; seconds must be between 1 and 30")
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        observer = session.create_script(probe_world_move.JS)
        observer.load()
        pointer = session.create_script(probe_pointer_click.JS)
        pointer.load()
        time.sleep(0.25)
        initial = observer.exports_sync.data()
        if not initial["samples"]:
            raise SystemExit("no player sample: " + str(initial["errors"]))
        click = pointer.exports_sync.click(args.x, args.y, 1280, 720)
        time.sleep(args.seconds)
        data = observer.exports_sync.stop()
    finally:
        session.detach()
    commands = [a for a in data["actions"] if a.get("kind") == "world_command"]
    samples = data["samples"]
    target = struct.unpack_from("<fff", bytes(commands[-1]["path"]), 8) if commands else None
    summary = {
        "start": samples[0]["pos"], "end": samples[-1]["pos"], "target": target,
        "distance": math.dist(samples[0]["pos"], samples[-1]["pos"]),
        "error": math.dist(samples[-1]["pos"][:2], target[:2]) if target else None,
        "commands": len(commands), "samples": len(samples),
        "zero_npad": all(s["axis"] == [0, 0] and s["buttons"] == "0" for s in samples),
        "zero_engine_input": all(s["engine"] == [0, 0] and s["nativeBits"] == 0 for s in samples),
        "errors": data["errors"],
    }
    summary["pass"] = bool(click["down"] and click["up"] and commands and
                           summary["distance"] > 0.5 and summary["error"] <= 0.15 and
                           summary["zero_npad"] and summary["zero_engine_input"] and
                           not summary["errors"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"build": build, "click": click, "summary": summary,
                                    "observation": data}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
