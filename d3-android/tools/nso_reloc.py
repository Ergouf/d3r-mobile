"""Resolve the symbol-bearing relocations of a Switch NSO.

The guest image this project maps was repacked by a tool that could not resolve
symbols, so it kept only R_AARCH64_RELATIVE entries and dropped every GLOB_DAT /
ABS64 record (the original main.nso carries 8 + 228 of them).  Those slots are
exactly the places where the SDK's own helpers come out as garbage at run time.

Usage:
  py -3 tools/nso_reloc.py <file.nso> [...]
"""

import struct
import sys

RELOC = {257: "ABS64", 258: "ABS32", 1025: "GLOB_DAT", 1026: "JUMP_SLOT", 1027: "RELATIVE"}
TAGNAME = {
    4: "HASH",
    5: "STRTAB",
    6: "SYMTAB",
    10: "STRSZ",
    11: "SYMENT",
    7: "RELA",
    8: "RELASZ",
    9: "RELAENT",
    20: "PLTRELSZ",
    23: "JMPREL",
}


def image_of(path):
    data = open(path, "rb").read()
    if data[:4] != b"NSO0":
        sys.exit(f"{path} is not an NSO")
    sections = [struct.unpack_from("<III", data, o) for o in (0x10, 0x20, 0x30)]
    image = bytearray()
    for offset, _mem, size in sections:
        while len(image) % 0x1000:
            image.append(0)
        image += data[offset : offset + size]
    return bytes(image)


def find_dynamic(image):
    """A DT_RELA/DT_RELASZ/DT_RELAENT triple identifies the table without trusting
    the module header layout, then the neighbouring tags are read around it."""
    for at in range(0, len(image) - 64, 16):
        tag0, value0 = struct.unpack_from("<QQ", image, at)
        tag1, value1 = struct.unpack_from("<QQ", image, at + 16)
        tag2, value2 = struct.unpack_from("<QQ", image, at + 32)
        if tag0 == 7 and tag1 == 8 and tag2 == 9 and value2 == 24 and 0 < value1 < len(image):
            entries = {}
            for probe in range(at - 0x200, at + 0x200, 16):
                if probe < 0 or probe + 16 > len(image):
                    continue
                tag, value = struct.unpack_from("<QQ", image, probe)
                if tag in TAGNAME and value < len(image):
                    entries.setdefault(tag, value)
            return entries
    return {}


def symbol_name(image, entries, index):
    symtab = entries.get(6)
    strtab = entries.get(5)
    if symtab is None or strtab is None:
        return None, 0, 0
    entry = symtab + index * 24
    if entry + 24 > len(image):
        return None, 0, 0
    name_offset, _info, _other, shndx, value, _size = struct.unpack_from("<IBBHQQ", image, entry)
    name = None
    if name_offset and strtab + name_offset < len(image):
        end = image.find(b"\0", strtab + name_offset)
        if end > 0:
            name = image[strtab + name_offset : end].decode("ascii", "replace")
    return name, shndx, value


def report(path):
    image = image_of(path)
    entries = find_dynamic(image)
    print(f"== {path.split(chr(92))[-1]} image {len(image):#x}")
    print("   dynamic:", {TAGNAME[t]: hex(v) for t, v in sorted(entries.items())})
    rela = entries.get(7)
    size = entries.get(8)
    if not rela or not size:
        print("   no RELA table found")
        return
    counts = {}
    named = []
    for at in range(rela, rela + size, 24):
        offset, info, addend = struct.unpack_from("<QQq", image, at)
        kind = info & 0xFFFFFFFF
        counts[kind] = counts.get(kind, 0) + 1
        if kind != 1027:
            name, shndx, value = symbol_name(image, entries, info >> 32)
            named.append((kind, offset, info >> 32, name, shndx, value, addend))
    print("   types:", {RELOC.get(k, hex(k)): v for k, v in sorted(counts.items())})
    print(f"   symbol relocations: {len(named)}")
    for kind, offset, index, name, shndx, value, addend in named:
        where = "UNDEF" if shndx == 0 else f"shndx={shndx} value={value:#x}"
        print(f"     {RELOC.get(kind, kind):<8} slot {offset:#08x} sym[{index}] {where} {name}")


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        report(argument)
