"""Report the relocation and dynamic tables of a Switch NSO (or of our repack).

The guest image this project maps carries only R_AARCH64_RELATIVE records, while
rtld resolves JUMP_SLOT/GLOB_DAT records out of a separate table; this dumps what
each file actually contains so the two can be compared.

Usage:
  py -3 tools/nso_info.py <file.nso|file.so> [...]
"""

import struct
import sys

TAGS = {
    4: "DT_HASH",
    5: "DT_STRTAB",
    6: "DT_SYMTAB",
    7: "DT_RELA",
    8: "DT_RELASZ",
    9: "DT_RELAENT",
    10: "DT_STRSZ",
    11: "DT_SYMENT",
    20: "DT_PLTRELSZ",
    23: "DT_JMPREL",
}

RELOCS = {
    257: "ABS64",
    258: "ABS32",
    1025: "GLOB_DAT",
    1026: "JUMP_SLOT",
    1027: "RELATIVE",
}


def read_nso(path):
    data = open(path, "rb").read()
    if data[:4] != b"NSO0":
        return None, data
    text_off, _tm, text_size = struct.unpack_from("<III", data, 0x10)
    ro_off, _rm, ro_size = struct.unpack_from("<III", data, 0x20)
    da_off, _dm, da_size = struct.unpack_from("<III", data, 0x30)
    sections = [("text", text_off, text_size), ("rodata", ro_off, ro_size), ("data", da_off, da_size)]
    # Assemble the memory image the module sees: text at 0, the rest page aligned.
    base = bytearray()
    layout = {}
    for name, offset, size in sections:
        while len(base) % 0x1000:
            base.append(0)
        layout[name] = (len(base), size)
        base += data[offset : offset + size]
    return (layout, bytes(base)), data


def module_base(image):
    """MOD0 sits at text+4 as a relative pointer; its header gives the dynamic table."""
    (pointer,) = struct.unpack_from("<I", image, 4)
    if image[pointer : pointer + 4] != b"MOD0":
        return None, 0
    (dynamic_offset,) = struct.unpack_from("<I", image, pointer + 4)
    return pointer, dynamic_offset


def dynamic_entries(image, dynamic_offset):
    entries = {}
    at = dynamic_offset
    while True:
        tag, value = struct.unpack_from("<QQ", image, at)
        if tag == 0:
            break
        entries.setdefault(tag, value)
        at += 16
    return entries


def report(path):
    described, raw = read_nso(path)
    print(f"== {path.split(chr(92))[-1]} ({len(raw)} bytes, magic {raw[:4]!r})")
    if described is None:
        # A plain ELF: read DT_* through the program headers.
        return report_elf(path, raw)
    layout, image = described
    print("   sections:", {k: (hex(v[0]), hex(v[1])) for k, v in layout.items()})
    pointer, dynamic_offset = module_base(image)
    if pointer is None:
        print("   MOD0 not found")
        return
    print(f"   MOD0 at {pointer:#x}, dynamic at {dynamic_offset:#x}")
    entries = dynamic_entries(image, dynamic_offset)
    for tag, value in sorted(entries.items()):
        print(f"   {TAGS.get(tag, hex(tag)):<10} {value:#x}")
    defin = entries.get(7, 0)
    size = entries.get(8, 0)
    if size:
        counts = {}
        for at in range(defin, defin + size, 24):
            _offset, info, _addend = struct.unpack_from("<QQq", image, at)
            kind = info & 0xFFFFFFFF
            counts[kind] = counts.get(kind, 0) + 1
        total = sum(counts.values())
        print(f"   DT_RELA entries: {total}")
        for kind, count in sorted(counts.items()):
            print(f"     {RELOCS.get(kind, kind):<10} {count}")
    if 23 in entries:
        print(f"   DT_JMPREL {entries[23]:#x} size {entries.get(20, 0):#x} (not counted)")


def report_elf(path, raw):
    print("   (ELF path: reading DT_* through program headers is done by tools/nso_elf_dyn.py)")


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        report(argument)
