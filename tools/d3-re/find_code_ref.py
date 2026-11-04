#!/usr/bin/env python3
"""Find ADRP+ADD (or ADRP+LDR) code references to exact guest addresses.

This is much faster than disassembling the whole text with Capstone: it decodes
only the two instruction encodings it needs, straight from the 4-byte words.

Usage:
  python tools/d3-re/find_code_ref.py 0x8dc985b
  python tools/d3-re/find_code_ref.py 0x8dc985b --window 8
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

TEXT = Path("out/windows/kbm/b2/runtime_text.bin")
GUEST_BASE = 0x8005000


def is_adrp(word: int) -> bool:
    return word & 0x9F000000 == 0x90000000


def adrp_target(word: int, pc: int) -> tuple[int, int]:
    immlo = (word >> 29) & 3
    immhi = (word >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    rd = word & 0x1F
    return (pc & ~0xFFF) + (imm << 12), rd


def add_target(word: int, page: int) -> tuple[int, int, int] | None:
    """Return (target, rn, rd) for ADD (imm, 64-bit, shift 0)."""
    if word & 0xFF800000 != 0x91000000:
        return None
    imm12 = (word >> 10) & 0xFFF
    rn = (word >> 5) & 0x1F
    rd = word & 0x1F
    return page + imm12, rn, rd


def ldr_target(word: int, page: int) -> tuple[int, int, int] | None:
    """Return (address, rn, rt) for LDR (unsigned offset, 64-bit)."""
    if word & 0xFFC00000 != 0xF9400000:
        return None
    imm12 = (word >> 10) & 0xFFF
    rn = (word >> 5) & 0x1F
    rt = word & 0x1F
    return page + imm12 * 8, rn, rt


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", type=lambda s: int(s, 0))
    ap.add_argument("--window", type=int, default=6, help="instructions to look ahead")
    args = ap.parse_args()
    blob = TEXT.read_bytes()
    words = struct.unpack_from(f"<{len(blob) // 4}I", blob)
    wanted = set(args.targets)
    for i, word in enumerate(words):
        if not is_adrp(word):
            continue
        pc = GUEST_BASE + i * 4
        page, rd = adrp_target(word, pc)
        for j in range(1, args.window + 1):
            if i + j >= len(words):
                break
            nxt = words[i + j]
            for fn in (add_target, ldr_target):
                got = fn(nxt, page)
                if got and got[0] in wanted and got[1] == rd:
                    print(f"0x{pc:08x} -> 0x{got[0]:08x} (insn {j} later, reg x{got[2]})")
                    wanted.discard(got[0])
                    break
            if got and got[0] in args.targets:
                break
        if not wanted:
            break
    for t in args.targets:
        if t in wanted:
            print(f"0x{t:08x}: no reference found")


if __name__ == "__main__":
    main()
