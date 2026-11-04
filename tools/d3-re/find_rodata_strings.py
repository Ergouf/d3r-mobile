#!/usr/bin/env python3
"""List ASCII strings in the dumped main rodata with guest addresses.

Usage:
  python tools/d3-re/find_rodata_strings.py --match "mouse|cursor" [-i] [--limit 50]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DEFAULT_RODATA = Path("out/windows/kbm/b2/runtime_rodata.bin")
RUNTIME_JSON = Path("out/windows/kbm/assessment-20261101/title-baseline.json")
MAIN_BASE = 0x8005000


def rodata_guest_base() -> int:
    if RUNTIME_JSON.exists():
        data = json.loads(RUNTIME_JSON.read_text(encoding="utf-8"))
        main = next(m for m in data["runtime"]["modules"] if m["name"] == "main")
        return int(main["base"], 0) + main["ro_off"]
    return MAIN_BASE + 0xC72C90


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rodata", type=Path, default=DEFAULT_RODATA)
    ap.add_argument("--match", default=".")
    ap.add_argument("--ignore-case", action="store_true", help="match case-insensitively")
    ap.add_argument("--min", type=int, default=4)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    blob = args.rodata.read_bytes()
    base = rodata_guest_base()
    flags = re.I if args.ignore_case else 0
    pattern = re.compile(args.match, flags)
    shown = 0
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % args.min, blob):
        text = m.group().decode("ascii")
        if not pattern.search(text):
            continue
        print(f"0x{base + m.start():08x}  {text}")
        shown += 1
        if shown >= args.limit:
            break
    print(f"-- {shown} match(es), rodata base 0x{base:08x}, {len(blob)} bytes")


if __name__ == "__main__":
    main()
