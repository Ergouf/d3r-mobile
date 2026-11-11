#!/usr/bin/env python3
"""Dump D3's script-function table from the fixed AArch64 ELF.

The table starts at module offset 0xd69d00 and has 0x30-byte entries:

    +0x00  u32  name offset (module-relative, points into .rodata)
    +0x08  u64  runtime slot (filled with the absolute function pointer)
    +0x10  u32  flags (0x403)
    +0x18  u64  function offset (module-relative)
    +0x20  u64  next name slot
    +0x28  u32  flags (0x403)

The first entries are the PowerCursor/Power script API. The function offset is
converted to an absolute guest address as 0x8005000 + offset. These functions
are standalone; their arguments arrive in a script argument object (see
windows/docs/KBM-RE-EVIDENCE.md).

Usage:
  python windows/d3-re/dump_script_table.py --filter Cursor --json out/windows/kbm/b1/script_table.json
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

DEFAULT_ELF = Path("out/windows/kbm/b0/d3_main_fixed.elf")
DEFAULT_BASE = 0xD69D00
STRIDE = 0x30
GUEST_BASE = 0x8005000


def load_segments(elf: Path) -> list[tuple[int, int, int]]:
    data = elf.read_bytes()
    phoff, = struct.unpack_from("<Q", data, 0x20)
    phnum, = struct.unpack_from("<H", data, 0x38)
    segments = []
    for i in range(phnum):
        _, _, off, va, _, fs, _, _ = struct.unpack_from("<IIQQQQQQ", data, phoff + i * 56)
        if fs:
            segments.append((va, off, fs))
    return data, segments


def read_va(data: bytes, segments: list[tuple[int, int, int]], va: int, size: int) -> bytes | None:
    for v, off, fs in segments:
        if v <= va < v + fs:
            start = off + (va - v)
            return data[start:start + size]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, default=DEFAULT_ELF)
    parser.add_argument("--base", type=lambda s: int(s, 0), default=DEFAULT_BASE)
    parser.add_argument("--count", type=int, default=3000)
    parser.add_argument("--filter", default=None, help="only names containing this text")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    data, segments = load_segments(args.elf)
    entries = []
    for i in range(args.count):
        off = args.base + i * STRIDE
        raw = read_va(data, segments, off, STRIDE)
        if raw is None:
            break
        name_off, = struct.unpack_from("<I", raw, 0)
        func_off, = struct.unpack_from("<Q", raw, 0x18)
        name_raw = read_va(data, segments, name_off, 120)
        if name_raw is None:
            continue
        name = name_raw.split(b"\0")[0].decode("latin1", "ignore")
        if not name or not all(32 <= ord(c) < 127 for c in name):
            continue
        if func_off >= 0xC72B90:
            continue
        entries.append({
            "entry": off,
            "name": name,
            "func_offset": func_off,
            "func_guest": GUEST_BASE + func_off,
        })

    if args.filter:
        needle = args.filter.lower()
        entries = [e for e in entries if needle in e["name"].lower()]

    for e in entries:
        print(f"{e['entry']:#x}  {e['name']:<55s} off={e['func_offset']:#x}  guest={e['func_guest']:#x}")
    print(f"{len(entries)} entries")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
