#!/usr/bin/env python3
"""Disassemble a range of the guest ELF by virtual address.

The guest image has no section headers (the text is only reachable through the
program headers), so objdump cannot walk it.  This maps a vaddr through the
PT_LOAD segments and prints capstone output with the vaddr of every line.
"""
import argparse
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def load_segments(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        sys.exit("%s is not ELF64 little endian" % path)
    (e_phoff,) = struct.unpack_from("<Q", data, 0x20)
    (e_phentsize,) = struct.unpack_from("<H", data, 0x36)
    (e_phnum,) = struct.unpack_from("<H", data, 0x38)
    segments = []
    for index in range(e_phnum):
        base = e_phoff + index * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, _ = (
            struct.unpack_from("<IIQQQQQQ", data, base)
        )
        if p_type == 1 and p_filesz:
            segments.append((p_vaddr, p_filesz, p_offset, p_flags))
    return data, segments


def read_vaddr(data, segments, vaddr, size):
    for p_vaddr, p_filesz, p_offset, _ in segments:
        if p_vaddr <= vaddr < p_vaddr + p_filesz:
            start = p_offset + (vaddr - p_vaddr)
            end = min(start + size, p_offset + p_filesz)
            return data[start:end]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("vaddr", type=lambda text: int(text, 0))
    parser.add_argument("size", type=lambda text: int(text, 0), nargs="?", default=0x200)
    args = parser.parse_args()

    data, segments = load_segments(args.image)
    code = read_vaddr(data, segments, args.vaddr, args.size)
    if code is None:
        sys.exit("vaddr %#x is not in a file-backed segment" % args.vaddr)
    disassembler = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    disassembler.detail = False
    for insn in disassembler.disasm(code, args.vaddr):
        print("%08x: %08x  %-8s %s" % (insn.address, insn.id and struct.unpack_from("<I", code, insn.address - args.vaddr)[0], insn.mnemonic, insn.op_str))


if __name__ == "__main__":
    main()
