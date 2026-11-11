#!/usr/bin/env python3
"""Find loads/stores that use a given small struct offset (displacement search).

Scans the dumped runtime text for LDR/STR (integer or SIMD&FP, 32/64-bit,
unsigned immediate) with the requested byte offset, and prints the hit
addresses grouped so a function can be identified.

Usage:
  python windows/d3-re/find_offset_access.py 0x378 0x37c 0x380 0x384
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

TEXT = Path("out/windows/kbm/b2/runtime_text.bin")
GUEST_BASE = 0x8005000


def decode(word: int) -> tuple[str, int, int] | None:
    """Return (kind, offset, rt) for LDR/STR immediate forms we care about."""
    # integer LDR/STR (unsigned offset): size bits 31:30, opc 29:27 patterns
    if word & 0x3B000000 == 0x39000000:  # LDR/STR (imm) 32/64-bit, unsigned
        size = (word >> 30) & 3
        load = (word >> 22) & 1
        if size not in (0, 2, 3):
            return None
        off = ((word >> 10) & 0xFFF) * (1 << size if size else 1)
        rt = word & 0x1F
        return ("ldr" if load else "str") + f".{8 << size}", off, rt
    # SIMD&FP LDR/STR (unsigned offset): 0x3D000000 family
    if word & 0x3B000000 == 0x3D000000:
        size = (word >> 30) & 3
        load = (word >> 22) & 1
        off = ((word >> 10) & 0xFFF) * (1 << size if size else 1)
        rt = word & 0x1F
        return ("fldr" if load else "fstr") + f".{8 << size}", off, rt
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("offsets", nargs="+", type=lambda s: int(s, 0))
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()
    blob = TEXT.read_bytes()
    words = struct.unpack_from(f"<{len(blob) // 4}I", blob)
    hits = {o: [] for o in args.offsets}
    for i, word in enumerate(words):
        got = decode(word)
        if not got:
            continue
        kind, off, rt = got
        if off in hits:
            hits[off].append((GUEST_BASE + i * 4, kind, rt))
    for off, rows in hits.items():
        print(f"== offset {off:#x}: {len(rows)} access(es)")
        for addr, kind, rt in rows[: args.limit]:
            print(f"  0x{addr:08x} {kind:7s} x{rt}")


if __name__ == "__main__":
    main()
