#!/usr/bin/env python3
"""Find 32/64-bit CMP (SUBS immediate) instructions against given constants.

Usage:
  python windows/d3-re/find_imm_cmp.py 0x6d7 0x6e7
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

TEXT = Path("out/windows/kbm/b2/runtime_text.bin")
GUEST_BASE = 0x8005000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("values", nargs="+", type=lambda s: int(s, 0))
    args = ap.parse_args()
    blob = TEXT.read_bytes()
    words = struct.unpack_from(f"<{len(blob) // 4}I", blob)
    wanted = {v: [] for v in args.values}
    for i, word in enumerate(words):
        # SUBS (immediate): 32-bit 0x71000000, 64-bit 0xB1000000; CMP == SUBS xzr
        top = word & 0xFFC00000
        if top in (0x71000000, 0xB1000000):
            imm = (word >> 10) & 0xFFF
            if imm in wanted and (word & 0x1F) == 0x1F:
                wanted[imm].append(GUEST_BASE + i * 4)
        # MOVZ/MOVK 16-bit constants are handled separately when needed.
    for value, addrs in wanted.items():
        print(f"== cmp #{value:#x}: {len(addrs)}")
        for a in addrs[:40]:
            print(f"  0x{a:08x}")


if __name__ == "__main__":
    main()
