#!/usr/bin/env python3
"""Annotate ADRP+ADD string references in the dumped runtime text.

Prints each string reference with the guest address of the ADRP and the next
few immediate constants, which helps identify table/registration functions.

Usage:
  python tools/d3-re/dis_stringrefs.py 0x84e7000 --count 4000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG

TEXT = Path("out/windows/kbm/b2/runtime_text.bin")
RODATA = Path("out/windows/kbm/b2/runtime_rodata.bin")
DATA = Path("out/windows/kbm/b2/runtime_data.bin")
RT_JSON = Path("out/windows/kbm/assessment-20261101/title-baseline.json")
GUEST_BASE = 0x8005000


def segment_bases() -> dict[str, tuple[bytes, int]]:
    runtime = json.loads(RT_JSON.read_text(encoding="utf-8"))
    main = next(m for m in runtime["runtime"]["modules"] if m["name"] == "main")
    base = int(main["base"], 0)
    return {
        "rodata": (RODATA.read_bytes(), base + main["ro_off"]),
        "data": (DATA.read_bytes(), base + main["data_off"]),
    }


def cstr(segments, guest: int) -> str | None:
    for blob, base in segments.values():
        off = guest - base
        if 0 <= off < len(blob):
            end = blob.find(b"\0", off, off + 160)
            if end > off:
                raw = blob[off:end]
                if all(32 <= c < 127 for c in raw):
                    return raw.decode("ascii")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("start", type=lambda s: int(s, 0))
    ap.add_argument("--count", type=int, default=200)
    args = ap.parse_args()
    data = TEXT.read_bytes()
    segments = segment_bases()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    start = args.start
    code = data[start - GUEST_BASE:start - GUEST_BASE + args.count * 4]
    insns = list(md.disasm(code, start))
    pending = None  # (page, insn addr, reg)
    for i, insn in enumerate(insns):
        text = None
        if insn.mnemonic == "adrp" and len(insn.operands) == 2 and insn.operands[0].type == ARM64_OP_REG:
            pending = (insn.operands[1].imm, insn.address, insn.operands[0].reg)
        elif insn.mnemonic == "add" and pending and len(insn.operands) == 3:
            dst, src, imm = insn.operands
            if src.type == ARM64_OP_REG and src.reg == pending[2] and imm.type == ARM64_OP_IMM:
                target = pending[0] + imm.imm
                text = cstr(segments, target)
                if text:
                    consts = []
                    for nxt in insns[i + 1:i + 6]:
                        if nxt.mnemonic == "mov" and len(nxt.operands) == 2 and nxt.operands[1].type == ARM64_OP_IMM:
                            consts.append(f"{nxt.op_str.split(',')[0].strip()}={nxt.operands[1].imm:#x}")
                        if nxt.mnemonic.startswith("bl"):
                            break
                    print(f"0x{insn.address:08x} -> 0x{target:08x} {text!r:<40} {' '.join(consts)}")
                pending = None
    print(f"-- {len(insns)} instructions from 0x{start:08x}")


if __name__ == "__main__":
    main()
