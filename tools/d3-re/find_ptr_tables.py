#!/usr/bin/env python3
"""Find runs of guest code pointers (jump/handler tables) in the data/rodata dumps.

Usage:
  python tools/d3-re/find_ptr_tables.py [--min 24]
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

B2 = Path("out/windows/kbm/b2")
INFO = json.loads((B2 / "runtime_info.json").read_text(encoding="utf-8"))["main"]
BASE = int(INFO["base"], 0)
TEXT_LO = BASE
TEXT_HI = BASE + INFO["text_size"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min", type=int, default=24)
    args = ap.parse_args()
    for name, off_key, size_key in (("rodata", "ro_off", "ro_size"), ("data", "data_off", "data_size")):
        blob = (B2 / f"runtime_{name}.bin").read_bytes()
        base = BASE + INFO[off_key]
        n = len(blob) // 8
        vals = struct.unpack_from(f"<{n}Q", blob)
        i = 0
        runs = []
        while i < n:
            if TEXT_LO <= vals[i] < TEXT_HI and vals[i] % 4 == 0:
                j = i
                while j < n and TEXT_LO <= vals[j] < TEXT_HI and vals[j] % 4 == 0:
                    j += 1
                if j - i >= args.min:
                    runs.append((base + i * 8, j - i))
                i = j
            else:
                i += 1
        print(f"== {name}: {len(runs)} run(s) >= {args.min}")
        for addr, count in runs[:40]:
            print(f"  0x{addr:08x}  {count} entries")


if __name__ == "__main__":
    main()
