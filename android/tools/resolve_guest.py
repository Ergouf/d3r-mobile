#!/usr/bin/env python3
"""Resolve a guest address: import thunks, and nearest SDK symbol.

The guest ELF keeps its function table behind GOT slots (adrp/ldr/br stubs) and
its text is not covered by section headers, so both the thunk target and the
symbol name need the RELA table and the leaked symbol map.
"""
import argparse
import bisect
import json
import os
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYMBOLS = os.path.join(ROOT, "reference", "d3-symbols", "sdk.symbols.json")
GUEST_BASE_DELTA = 0x10000


class GuestImage:
    def __init__(self, path):
        with open(path, "rb") as handle:
            self.data = handle.read()
        header = self.data
        if header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1:
            sys.exit("%s is not ELF64 little endian" % path)
        (e_phoff,) = struct.unpack_from("<Q", header, 0x20)
        (e_phentsize,) = struct.unpack_from("<H", header, 0x36)
        (e_phnum,) = struct.unpack_from("<H", header, 0x38)
        self.segments = []
        self.dynamic = None
        for index in range(e_phnum):
            base = e_phoff + index * e_phentsize
            (p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz, _memsz, _align) = (
                struct.unpack_from("<IIQQQQQQ", header, base)
            )
            if p_type == 1 and p_filesz:
                self.segments.append((p_vaddr, p_offset, p_filesz))
            elif p_type == 2:
                self.dynamic = (p_vaddr, p_filesz)
        self.relocations = {}
        self._load_relocations()

    def _load_relocations(self):
        if not self.dynamic:
            return
        rela = relasz = relaent = 0
        offset = self.file_offset(self.dynamic[0])
        for index in range(self.dynamic[1] // 16):
            tag, value = struct.unpack_from("<QQ", self.data, offset + 16 * index)
            if tag == 0:
                break
            if tag == 7:
                rela = value
            elif tag == 8:
                relasz = value
            elif tag == 9:
                relaent = value
        if not relaent:
            return
        start = self.file_offset(rela)
        for index in range(relasz // relaent):
            r_offset, _info, r_addend = struct.unpack_from(
                "<QQq", self.data, start + relaent * index
            )
            self.relocations[r_offset] = r_addend

    def file_offset(self, vaddr):
        for p_vaddr, p_offset, p_filesz in self.segments:
            if p_vaddr <= vaddr < p_vaddr + p_filesz:
                return p_offset + (vaddr - p_vaddr)
        return None

    def bytes_at(self, vaddr, size):
        offset = self.file_offset(vaddr)
        if offset is None:
            return None
        return self.data[offset:offset + size]

    def imported_target(self, thunk):
        """The function a GOT thunk jumps to, or None if it is real code."""
        code = self.bytes_at(thunk, 16)
        if not code:
            return None
        disassembler = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        disassembler.detail = True
        instructions = list(disassembler.disasm(code, thunk))
        if len(instructions) < 4 or instructions[0].mnemonic != "adrp":
            return None
        if instructions[1].mnemonic != "ldr" or instructions[3].mnemonic != "br":
            return None
        if not instructions[0].operands[0].reg == instructions[1].operands[1].reg:
            return None
        page = instructions[0].operands[1].imm
        slot = page + instructions[1].operands[1].mem.disp
        return self.relocations.get(slot)


def load_symbols(path):
    raw = open(path, "rb").read().decode("utf-8")
    pairs = json.loads(raw, object_pairs_hook=lambda kv: kv)
    by_address = sorted((value, name) for name, value in pairs if isinstance(value, int))
    return [address for address, _ in by_address], by_address


def symbol_for(addresses, by_address, guest_vaddr):
    image_vaddr = guest_vaddr - GUEST_BASE_DELTA
    index = bisect.bisect_right(addresses, image_vaddr) - 1
    if index < 0:
        return None
    base, name = by_address[index]
    return name, image_vaddr - base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("vaddr", type=lambda text: int(text, 0))
    parser.add_argument("--symbols", default=SYMBOLS)
    args = parser.parse_args()

    image = GuestImage(args.image)
    target = image.imported_target(args.vaddr)
    if target is not None:
        print("thunk %#x -> %#x" % (args.vaddr, target))
        resolved = target
    else:
        resolved = args.vaddr
    addresses, by_address = load_symbols(args.symbols)
    found = symbol_for(addresses, by_address, resolved)
    if found:
        name, delta = found
        print("%s+%#x" % (name, delta) if delta else name)
    else:
        print("%#x (no symbol)" % resolved)


if __name__ == "__main__":
    main()
