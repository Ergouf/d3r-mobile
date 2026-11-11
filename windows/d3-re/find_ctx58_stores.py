#!/usr/bin/env python3
"""List stores that can write the TLS context's ``+0x58`` field (the actor-id table owner).

``0x8828460`` needs ``[ctx+0x58] -> [+0x618] -> [+8]``; in the live town state ``[ctx+0x58]``
is 0 for every thread, so the table is never created.  This is a static first pass at finding
who could write it: every ``str x?, [x?, #0x58]`` and every ``stp`` whose immediate covers
``+0x58`` (``#0x50`` second register, ``#0x58`` first register) in the saved main-module text,
with a count of how many sit within 0x400 bytes of a ``0x800E3D0`` (GetTlsValue) call site.

The listing is candidates only: it does not prove which store targets the TLS context object,
and a store that never runs cannot be the answer.

Usage:
  python windows/d3-re/find_ctx58_stores.py [--text out/windows/kbm/b2/runtime_text.bin]
"""
from __future__ import annotations

import argparse
import re
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

BASE = 0x8005000
GETTER = 0x800E3D0
WINDOW = 0x400


def getter_calls(data: bytes) -> list[int]:
    sites = []
    for off in range(0, len(data) - 4, 4):
        word = struct.unpack_from("<I", data, off)[0]
        if (word & 0xFC000000) == 0x94000000:
            imm = word & 0x03FFFFFF
            if imm & 0x02000000:
                imm -= 0x04000000
            pc = BASE + off
            if pc + imm * 4 == GETTER:
                sites.append(pc)
    return sites


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", default="out/windows/kbm/b2/runtime_text.bin")
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()

    data = open(args.text, "rb").read()
    bls = getter_calls(data)
    print(f"getter BL sites: {len(bls)}")

    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.skipdata = True
    groups = {
        "str #0x58": re.compile(r"\[x\d+, #0x58\]"),
        "stp #0x50": re.compile(r"\[x\d+, #0x50\]"),
        "stp #0x58": re.compile(r"\[x\d+, #0x58\]"),
    }
    hits: dict[str, list[tuple[int, str]]] = {k: [] for k in groups}
    for ins in md.disasm(data, BASE):
        if ins.mnemonic == "str" and groups["str #0x58"].search(ins.op_str):
            hits["str #0x58"].append((ins.address, ins.op_str))
        elif ins.mnemonic == "stp":
            for name in ("stp #0x50", "stp #0x58"):
                if groups[name].search(ins.op_str):
                    hits[name].append((ins.address, ins.op_str))
    for name, rows in hits.items():
        near = [(a, o) for a, o in rows if any(abs(b - a) <= WINDOW for b in bls)]
        print(f"{name}: {len(rows)} sites, {len(near)} within 0x{WINDOW:x} of a getter call")
        for addr, ops in near[: args.limit]:
            print(f"   0x{addr:08x}: {ops}")


if __name__ == "__main__":
    main()
