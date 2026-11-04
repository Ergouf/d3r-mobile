"""Decode the engine input-manager mapping tables dumped by dump_guest.py.

Layout taken from the manager loop at 0x80FD7E4..0x80FD864:
  entries start at table + 0x70, stride 0x38, at most 16
  +0x00 mask64      (device +0x30 is ANDed with it)
  +0x08 expected64  (the masked value must equal this to set the bit)
  +0x10 bit index   (logical bit set/cleared in player +0x36C)
  +0x18 reserved
The two tables sit 0x380 apart and are selected by the manager's
"docked/handheld" flag (w12 = (w0 != 0)).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_bytes()
for t in range(2):
    base = t * 0x380
    print(f"== table {t} (offset {base:#x}) ==")
    for n in range(16):
        off = base + 0x70 + n * 0x38
        if off + 0x20 > len(raw):
            break
        mask, expected, bit, extra = struct.unpack_from("<QQQQ", raw, off)
        if mask == 0 and expected == 0 and bit == 0:
            print(f"  [{n:2d}] empty")
            continue
        print(f"  [{n:2d}] mask={mask:#018x} expect={expected:#018x} "
              f"bit={bit & 0xffffffff} extra={extra:#018x}")
