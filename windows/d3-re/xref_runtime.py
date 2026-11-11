#!/usr/bin/env python3
"""Find address and direct-branch references in runtime main text.

Targets and output use absolute guest addresses (main base is 0x8005000).
Embedded data is skipped rather than silently ending the scan. These are
candidate xrefs from a linear sweep, not a replacement for CFG analysis.

Usage:
  python windows/d3-re/xref_runtime.py 0x81a8588 0x81511cb
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG

DEFAULT_TEXT = Path("out/windows/kbm/b2/runtime_text.bin")
GUEST_BASE = 0x8005000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", type=lambda s: int(s, 0))
    ap.add_argument("--text", type=Path, default=DEFAULT_TEXT)
    ap.add_argument("--json", type=Path, help="Save hits and scan coverage; print only the summary")
    args = ap.parse_args()
    targets = set(args.targets)

    data = args.text.read_bytes()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    pages: dict[int, tuple[int, int]] = {}  # reg -> (page, insn address)
    hits = []
    instructions = skipped = consumed = 0
    started = time.perf_counter()
    for insn in md.disasm(data, GUEST_BASE):
        consumed = insn.address + insn.size - GUEST_BASE
        if insn.id == 0:
            skipped += insn.size
            pages.clear()
            continue
        instructions += 1
        pages = {r: item for r, item in pages.items() if insn.address - item[1] <= 32}
        resolved = None
        if insn.mnemonic == "adrp" and len(insn.operands) == 2:
            dst, imm = insn.operands
            if dst.type == ARM64_OP_REG and imm.type == ARM64_OP_IMM:
                pages[dst.reg] = (imm.imm, insn.address)
            continue
        if insn.mnemonic == "add" and len(insn.operands) >= 3:
            dst, src, off = insn.operands[0], insn.operands[1], insn.operands[2]
            if src.type == ARM64_OP_REG and src.reg in pages and off.type == ARM64_OP_IMM and dst.type == ARM64_OP_REG:
                page, at = pages[src.reg]
                target = page + (off.imm << off.shift.value)
                if target in targets:
                    resolved = (target, at)
        if insn.mnemonic.startswith(("ldr", "str")) and len(insn.operands) >= 2:
            mem = insn.operands[1]
            if mem.type == ARM64_OP_MEM and mem.mem.base in pages and not mem.mem.index:
                page, at = pages[mem.mem.base]
                target = page + mem.mem.disp
                if target in targets:
                    resolved = (target, at)
        if insn.mnemonic == "adr" and len(insn.operands) == 2 and insn.operands[1].type == ARM64_OP_IMM:
            if insn.operands[1].imm in targets:
                resolved = (insn.operands[1].imm, None)
        if insn.mnemonic in ("bl", "b") and len(insn.operands) == 1 and insn.operands[0].type == ARM64_OP_IMM:
            if insn.operands[0].imm in targets:
                resolved = (insn.operands[0].imm, None)
        if resolved:
            target, at = resolved
            record = {"target": target, "at": insn.address, "instruction": insn.mnemonic + " " + insn.op_str,
                      "adrp_at": at}
            hits.append(record)
            if not args.json:
                print(f"{target:#x} <- {insn.address:#x} ({record['instruction']})")
        # a register written by anything else is no longer a page
        for reg in insn.regs_access()[1]:
            pages.pop(reg, None)
        if insn.mnemonic in ("b", "bl", "br", "blr", "ret") or insn.mnemonic.startswith(("b.", "cb", "tb")):
            pages.clear()
    result = {"base": GUEST_BASE, "total_bytes": len(data), "consumed_bytes": consumed,
              "skipped_data_bytes": skipped, "decoded_instructions": instructions,
              "elapsed_seconds": round(time.perf_counter() - started, 3), "hits": hits}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Scanned {consumed}/{len(data)} bytes; skipped {skipped} data bytes; {len(hits)} candidate xrefs; "
          f"{result['elapsed_seconds']} s")


if __name__ == "__main__":
    main()
