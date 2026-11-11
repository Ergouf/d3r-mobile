#!/usr/bin/env python3
"""Find MOVZ/MOVK immediate loads of given 16-bit constants.

Usage:
  python windows/d3-re/find_imm_mov.py 0x6d7 0x6e7
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
        opc = (word >> 23) & 0xFF
        # movz: opc 0b10 100101, movn 0b00 100101, movk 0b11 100101
        if opc in (0x52, 0x12, 0x72, 0x92, 0xD2, 0xF2):
            imm16 = (word >> 5) & 0xFFFF
            if imm16 in wanted:
                wanted[imm16].append((GUEST_BASE + i * 4, word))
    for value, hits in wanted.items():
        print(f"== mov imm #{value:#x}: {len(hits)}")
        for addr, word in hits[:40]:
            kind = {0x52: "movz w", 0xD2: "movz x", 0x72: "movk w", 0xF2: "movk x",
                    0x12: "movn w", 0x92: "movn x"}.get((word >> 23) & 0xFF, "?")
            print(f"  0x{addr:08x} {kind}{word & 0x1F}")


if __name__ == "__main__":
    main()
