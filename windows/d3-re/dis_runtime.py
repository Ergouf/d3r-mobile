#!/usr/bin/env python3
"""Disassemble the runtime-dumped main text at guest addresses.

The fixed ELF's text does not match the installed runtime; this reads the
`runtime_text.bin` dump from `windows/d3-re/dump_runtime_code.py` instead and
prints AArch64 instructions around one or more guest addresses.

Usage:
  python windows/d3-re/dis_runtime.py 0x83b70c0 --count 80
"""
from __future__ import annotations

import argparse
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

DEFAULT_TEXT = Path("out/windows/kbm/b2/runtime_text.bin")
GUEST_BASE = 0x8005000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("addresses", nargs="+", type=lambda s: int(s, 0))
    ap.add_argument("--text", type=Path, default=DEFAULT_TEXT)
    ap.add_argument("--count", type=int, default=64)
    ap.add_argument("--before", type=int, default=0)
    args = ap.parse_args()

    data = args.text.read_bytes()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    for addr in args.addresses:
        off = addr - GUEST_BASE - args.before * 4
        start = addr - args.before * 4
        print(f"=== {addr:#x} (file {off:#x}) ===")
        for insn in md.disasm(data[off:off + (args.count + args.before) * 4], start):
            mark = ">>" if insn.address == addr else "  "
            print(f"{mark} {insn.address:#010x}: {insn.mnemonic:<8} {insn.op_str}")


if __name__ == "__main__":
    main()
