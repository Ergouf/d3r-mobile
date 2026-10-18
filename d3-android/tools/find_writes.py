"""Find instructions that write a given guest object (adrp + str pair).

The guest sdk keeps its singletons in .bss, so "who initialises this?" is a
search for the adrp/add that materialises the object followed by a store.  No
symbols are needed and the scan covers the whole executable segment.

Usage:
  py -3 tools/find_writes.py <guest.so> <object-vaddr> [context-instructions]
"""

import struct
import sys


def load(path):
    data = open(path, "rb").read()
    (e_phoff,) = struct.unpack_from("<Q", data, 0x20)
    (e_phentsize,) = struct.unpack_from("<H", data, 0x36)
    (e_phnum,) = struct.unpack_from("<H", data, 0x38)
    segments = []
    for index in range(e_phnum):
        base = e_phoff + index * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, _pa, p_filesz, _msz, _al = struct.unpack_from(
            "<IIQQQQQQ", data, base
        )
        if p_type == 1 and p_filesz and p_flags & 1:
            segments.append((p_vaddr, data[p_offset : p_offset + p_filesz]))
    return segments


def decode_adrp(word, pc):
    if word & 0x9F000000 != 0x90000000:
        return None
    immlo = (word >> 29) & 3
    immhi = (word >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    return ((pc & ~0xFFF) + (imm << 12)) & 0xFFFFFFFFFFFFFFFF


def main(argv):
    path = argv[0]
    target = int(argv[1], 0)
    context = int(argv[2], 0) if len(argv) > 2 else 8
    page = target & ~0xFFF
    offset = target & 0xFFF
    imm12 = offset // 8
    for seg_vaddr, chunk in load(path):
        for at in range(0, len(chunk) - 3, 4):
            word = struct.unpack_from("<I", chunk, at)[0]
            pc = seg_vaddr + at
            if decode_adrp(word, pc) != page:
                continue
            reg = word & 31
            for step in range(1, context + 1):
                off = at + step * 4
                if off + 4 > len(chunk):
                    break
                other = struct.unpack_from("<I", chunk, off)[0]
                # str x?, [xR, #imm]  (64 bit) or str w?, [xR, #imm]
                if other & 0xFFC00000 in (0xF9000000, 0xB9000000):
                    rn = (other >> 5) & 31
                    imm = (other >> 10) & 0xFFF
                    if rn == reg and imm * (4 if other & 0xFFC00000 == 0xB9000000 else 8) == offset:
                        kind = "str w" if other & 0xFFC00000 == 0xB9000000 else "str x"
                        print(f"{kind} -> {target:#x} at {seg_vaddr + off:#x} (adrp at {pc:#x})")
                # add xR, xR, #imm 3 shifted (movz/movk pairs are ignored)
                if other & 0xFF800000 == 0x91000000:
                    rn = (other >> 5) & 31
                    rd = other & 31
                    imm = (other >> 10) & 0xFFF
                    if rn == reg and imm == offset:
                        print(f"add -> {target:#x} at {seg_vaddr + off:#x} (adrp at {pc:#x})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
