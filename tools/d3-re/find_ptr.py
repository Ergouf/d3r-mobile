#!/usr/bin/env python3
"""Find 8-byte little-endian pointers to one or more guest addresses in the dumps.

Usage:
  python tools/d3-re/find_ptr.py 0x08dc985b 0x08e26e0b
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

B2 = Path("out/windows/kbm/b2")
INFO = B2 / "runtime_info.json"


def segments() -> dict[str, tuple[bytes, int]]:
    info = json.loads(INFO.read_text(encoding="utf-8"))["main"]
    base = int(info["base"], 0)
    return {
        "rodata": ((B2 / "runtime_rodata.bin").read_bytes(), base + info["ro_off"]),
        "data": ((B2 / "runtime_data.bin").read_bytes(), base + info["data_off"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", type=lambda s: int(s, 0))
    ap.add_argument("--width", type=int, default=8, help="pointer width in bytes (8 or 4)")
    args = ap.parse_args()
    segs = segments()
    for target in args.targets:
        needle = target.to_bytes(args.width, "little")
        print(f"== 0x{target:08x} ({args.width} bytes)")
        hits = 0
        for name, (blob, base) in segs.items():
            off = blob.find(needle)
            while off != -1:
                print(f"  {name} 0x{base + off:08x}  (file +0x{off:x})")
                hits += 1
                off = blob.find(needle, off + 1)
        if not hits:
            print("  no hits")


if __name__ == "__main__":
    main()
