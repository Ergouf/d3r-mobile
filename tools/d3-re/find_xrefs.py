#!/usr/bin/env python3
"""Find AArch64 code references to a module-relative address in d3_main_fixed.elf.

The ELF is built from main.nso0 with Ghidra addresses equal to module offsets,
so a string at file offset X (inside .rodata) has the same value as its module
offset.  This tool scans .text with capstone and resolves ADRP+ADD / ADRP+LDR
pairs, plus ADR, to that address.

Examples:
    python tools/d3-re/find_xrefs.py 0xdc51cb
    python tools/d3-re/find_xrefs.py --string ControlScheme
    python tools/d3-re/find_xrefs.py --string ControlScheme --guest
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
from elftools.elf.elffile import ELFFile


def load_sections(path: Path):
    with path.open("rb") as f:
        elf = ELFFile(f)
        text = elf.get_section_by_name(".text")
        rodata = elf.get_section_by_name(".rodata")
        if text is None:
            raise SystemExit("no .text section")
        return (
            text.data(),
            text["sh_addr"],
            rodata.data() if rodata is not None else b"",
            rodata["sh_addr"] if rodata is not None else 0,
        )


def find_string(rodata: bytes, rodata_addr: int, needle: str, exact: bool):
    raw = needle.encode()
    hits = []
    start = 0
    while True:
        i = rodata.find(raw, start)
        if i < 0:
            break
        before = rodata[i - 1] if i else 0
        after = rodata[i + len(raw)] if i + len(raw) < len(rodata) else 0
        if exact:
            if (before == 0 or before < 0x20) and (after == 0 or after < 0x20):
                hits.append((rodata_addr + i, i))
        else:
            hits.append((rodata_addr + i, i))
        start = i + 1
    return hits


def scan(text: bytes, text_addr: int, targets: set[int]):
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    md.skipdata = True
    pages: dict[int, int] = {}
    hits: list[tuple[int, int]] = []

    for insn in md.disasm(text, text_addr):
        if insn.id == 0:
            continue
        mnem = insn.mnemonic
        ops = insn.operands
        if mnem == "adrp" and len(ops) == 2 and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_IMM:
            pages[ops[0].reg] = ops[1].imm
            continue
        if mnem in ("add", "adds") and len(ops) >= 3:
            base, imm = ops[1], ops[2]
            if base.type == ARM64_OP_REG and base.reg in pages and imm.type == ARM64_OP_IMM:
                addr = pages[base.reg] + imm.imm
                if addr in targets:
                    hits.append((insn.address, addr))
        if mnem in ("ldr", "str", "ldrb", "ldrh", "ldrsw", "ldrsb", "ldrsh") and len(ops) >= 2:
            base = ops[1]
            if base.type == ARM64_OP_MEM and base.mem.base in pages:
                addr = pages[base.mem.base] + base.mem.disp
                if addr in targets:
                    hits.append((insn.address, addr))
        if mnem == "adr" and len(ops) == 2 and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_IMM:
            if ops[1].imm in targets:
                hits.append((insn.address, ops[1].imm))
        if mnem in ("bl", "b") and len(ops) == 1 and ops[0].type == ARM64_OP_IMM:
            if ops[0].imm in targets:
                hits.append((insn.address, ops[0].imm))
        # A page register reused after a branch may be stale; capstone's linear
        # sweep is good enough here because the compiler keeps ADRP close to use.
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", type=lambda s: int(s, 0))
    ap.add_argument("--elf", default="out/windows/kbm/b0/d3_main_fixed.elf")
    ap.add_argument("--string", help="find references to this string instead of a numeric target")
    ap.add_argument("--exact", action="store_true", help="require NUL/space around --string")
    ap.add_argument("--guest", action="store_true", help="print absolute guest addresses (+0x8005000)")
    args = ap.parse_args()

    text, text_addr, rodata, rodata_addr = load_sections(Path(args.elf))
    targets = set(args.targets)
    names: dict[int, str] = {}
    if args.string:
        for addr, off in find_string(rodata, rodata_addr, args.string, args.exact):
            targets.add(addr)
            names[addr] = f"{args.string}@{off:#x}"
    if not targets:
        ap.error("give at least one target address or --string")
    for t, n in sorted(names.items()):
        print(f"string {n} target={t:#x}")
    hits = scan(text, text_addr, targets)
    base = 0x8005000 if args.guest else 0
    for at, target in hits:
        label = names.get(target, "")
        print(f"xref {at + base:#x} (module {at:#x}) -> {target + base:#x} {label}")
    print(f"{len(hits)} xref(s), {len(targets)} target(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
