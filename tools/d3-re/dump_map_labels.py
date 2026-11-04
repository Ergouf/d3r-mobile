#!/usr/bin/env python3
"""Print the rodata strings that the input mapping tables point at.

Usage:
  python tools/d3-re/dump_map_labels.py
"""
from __future__ import annotations

import json
from pathlib import Path

B2 = Path("out/windows/kbm/b2")
RUNTIME = json.loads((B2 / "runtime_info.json").read_text(encoding="utf-8"))["main"]
BASE = int(RUNTIME["base"], 0)
RO_BASE = BASE + RUNTIME["ro_off"]
RO = (B2 / "runtime_rodata.bin").read_bytes()

# table 0 entries: (bit, label pointer) as decoded from map-tables-full.bin
LABELS = [
    (0, 0x8e24592), (1, 0x8e3e883), (2, 0x8e5fd74), (3, 0x8e245b5),
    (4, 0x8e72be9), (5, 0x8dd3927), (6, 0x8e58cb4), (7, 0x8e9333f),
    (8, 0x8e8cc2a), (9, 0x8e1deea), (10, 0x8e516e0), (11, 0x8e16fb5),
    (12, 0x8de7102), (13, 0x8dda2f1), (14, 0x8dee7ab), (15, 0x8e10372),
]


def cstr(guest: int) -> str:
    off = guest - RO_BASE
    if not (0 <= off < len(RO)):
        return "<outside rodata>"
    end = RO.find(b"\0", off, off + 80)
    return RO[off:end].decode("ascii", "replace")


for bit, ptr in LABELS:
    print(f"bit {bit:2d} 0x{ptr:08x}  {cstr(ptr)!r}")
