#!/usr/bin/env python3
"""List ASCII strings in the dumped main rodata with guest addresses.

Segment bases are read from the runtime_info.json that sits next to the dump
("main".base + "main".ro_off). A different dump therefore needs its own
metadata file, or an explicit guest base via --base.

Usage:
  python windows/d3-re/find_rodata_strings.py --match "mouse|cursor" [-i] [--limit 50]
  python windows/d3-re/find_rodata_strings.py --rodata some/rodata.bin --base 0x8c9d000
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DEFAULT_RODATA = Path("out/windows/kbm/b2/runtime_rodata.bin")
INFO_NAME = "runtime_info.json"


def as_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected integer, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"{field}: expected integer or numeric string, got {type(value).__name__}")


def load_main_info(info_path: Path) -> dict:
    if not info_path.is_file():
        raise SystemExit(
            f"error: metadata not found: {info_path}. "
            "Point --rodata at a dump that has runtime_info.json beside it, or pass --base."
        )
    data = json.loads(info_path.read_text(encoding="utf-8"))
    main = data.get("main")
    if not isinstance(main, dict):
        raise SystemExit(f"error: {info_path}: no 'main' record")
    return main


def rodata_guest_base(rodata: Path, base_override: int | None, info_override: Path | None) -> tuple[int, str]:
    if base_override is not None:
        return base_override, "explicit --base"
    info_path = info_override or (rodata.parent / INFO_NAME)
    main = load_main_info(info_path)
    base = as_int(main.get("base"), "main.base")
    ro_off = as_int(main.get("ro_off"), "main.ro_off")
    return base + ro_off, str(info_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rodata", type=Path, default=DEFAULT_RODATA)
    ap.add_argument("--info", type=Path, default=None, help="runtime_info.json (default: beside --rodata)")
    ap.add_argument("--base", type=lambda s: int(s, 0), default=None,
                    help="explicit guest address of rodata[0]; skips metadata lookup")
    ap.add_argument("--match", default=".")
    ap.add_argument("--ignore-case", action="store_true", help="match case-insensitively")
    ap.add_argument("--min", type=int, default=4)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    if not args.rodata.is_file():
        raise SystemExit(f"error: rodata dump not found: {args.rodata}")
    base, source = rodata_guest_base(args.rodata, args.base, args.info)
    blob = args.rodata.read_bytes()
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
    print(f"-- {shown} match(es), rodata base 0x{base:08x} ({source}), {len(blob)} bytes")


if __name__ == "__main__":
    main()
