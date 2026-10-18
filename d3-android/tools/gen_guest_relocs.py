"""Generate the relocation records the repacked guest image lost.

The mapped `libd3guest.so` was produced by a tool that applied only
R_AARCH64_RELATIVE records, so the 236 symbol-bearing records (228 ABS64 for
__cxa_pure_virtual, 4 GLOB_DAT for __rel_*) and the 342 JUMP_SLOT imports are
left unwritten and every call through them fails.  This reads the original
`main` NSO (base and update builds), resolves each record's symbol name, and
emits a table in merged-image offsets for the host to apply at load time.

Merged layout (guest_layout.h): sdk at 0x10000, main at 0x1000000.

Usage:
  py -3 tools/gen_guest_relocs.py --probe
  py -3 tools/gen_guest_relocs.py --emit host/guest_relocs.h
"""

import argparse
import json
import struct
import sys
from pathlib import Path

MAIN_BASE = 0x01000000
SDK_BASE = 0x00010000  # symbol file offsets are sdk-module relative
ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = str(ROOT / "reference" / "d3-symbols" / "sdk.symbols.json")
BASE_MAIN = str(ROOT / "reference" / "extract" / "exefs" / "main.nso0")
UPDATE_MAIN = str(ROOT / "reference" / "extract" / "exefs_update" / "main.nso0")

RELATIVE = 1027
GLOB_DAT = 1025
ABS64 = 257
JUMP_SLOT = 1026


def image_of(path):
    data = open(path, "rb").read()
    if data[:4] != b"NSO0":
        sys.exit(f"{path}: not an NSO")
    image = bytearray()
    for offset in (0x10, 0x20, 0x30):
        file_offset, _mem, size = struct.unpack_from("<III", data, offset)
        while len(image) % 0x1000:
            image.append(0)
        image += data[file_offset : file_offset + size]
    return bytes(image)


def find_relocation_runs(image, kind, minimum=64, window=(0x800000, 0x1400000)):
    """Locate a table by a long run of 24-byte records of one relocation type."""
    runs = []
    start = None
    count = 0
    for at in range(window[0], min(window[1], len(image) - 24), 8):
        _offset, info, _addend = struct.unpack_from("<QQq", image, at)
        if info & 0xFFFFFFFF == kind:
            if start is None or at != start + count * 24:
                start = at
                count = 1
            else:
                count += 1
            if count == minimum and start is not None:
                runs.append((start, count))
        # keep scanning: a longer run extends the same start
    return runs


def records(image, start, count, kinds):
    out = []
    for index in range(count):
        offset, info, addend = struct.unpack_from("<QQq", image, start + index * 24)
        kind = info & 0xFFFFFFFF
        if kind in kinds:
            out.append((kind, offset, info >> 32, addend))
    return out


def dynamic_tables(image):
    """MOD0 points at the module's dynamic table; one 8-byte header is followed by
    16-byte entries (tag in the low 32 bits, then the value)."""
    pointer = struct.unpack_from("<I", image, 4)[0]
    if image[pointer : pointer + 4] != b"MOD0":
        return {}
    dynamic = struct.unpack_from("<I", image, pointer + 4)[0] + 8
    entries = {}
    at = dynamic
    while at + 16 <= len(image):
        tag = struct.unpack_from("<I", image, at)[0]
        value = struct.unpack_from("<Q", image, at + 8)[0]
        if tag == 0:
            break
        if value < len(image):
            entries.setdefault(tag, value)
        at += 16
    return entries


def symbol_name(image, entries, index):
    symtab = entries.get(6)
    strtab = entries.get(5)
    if symtab is None or strtab is None:
        return None
    entry = symtab + index * 24
    if entry + 24 > len(image):
        return None
    name_offset = struct.unpack_from("<I", image, entry)[0]
    if not name_offset or strtab + name_offset >= len(image):
        return None
    end = image.find(b"\0", strtab + name_offset)
    if end <= 0:
        return None
    return image[strtab + name_offset : end].decode("ascii", "replace")


def walk(image, start, kind, limit=10000):
    """Walk a relocation table from its first record while the type matches."""
    out = []
    at = start
    for _ in range(limit):
        if at + 24 > len(image):
            break
        offset, info, addend = struct.unpack_from("<QQq", image, at)
        if info & 0xFFFFFFFF != kind:
            break
        out.append((offset, info >> 32, addend))
        at += 24
    return out


def scan_kind(image, kind, window, limit=64):
    out = []
    for at in range(window[0], min(window[1], len(image) - 24), 8):
        offset, info, addend = struct.unpack_from("<QQq", image, at)
        if info & 0xFFFFFFFF == kind and offset < len(image):
            out.append((offset, info >> 32, addend))
            if len(out) >= limit:
                break
    return out


def emit(path_out):
    symbols = json.load(open(SYMBOLS))
    update_image = image_of(UPDATE_MAIN)
    entries = dynamic_tables(update_image)
    rela, rela_size = entries[7], entries[8]
    jump, jump_size = entries[23], entries[2]
    print(f"update dynamic: RELA {rela:#x}/{rela_size:#x} JMPREL {jump:#x}/{jump_size:#x} "
          f"SYMTAB {entries[6]:#x} STRTAB {entries[5]:#x}")

    rows = []
    unresolved = []
    counts = {}
    rela_start, rela_bytes = 0x3180058, 0x200460
    for at in range(rela, rela + rela_size, 24):
        slot, info, _addend = struct.unpack_from("<QQq", update_image, at)
        kind = info & 0xFFFFFFFF
        counts[kind] = counts.get(kind, 0) + 1
        if kind == RELATIVE:
            continue
        name = symbol_name(update_image, entries, info >> 32)
        if name in ("__rel_dyn_start", "__rel_plt_start"):
            rows.append((MAIN_BASE + slot, rela_start, name))
            continue
        if name in ("__rel_dyn_end", "__rel_plt_end"):
            rows.append((MAIN_BASE + slot, rela_start + rela_bytes, name))
            continue
        target = symbols.get(name)
        if target is not None:
            target += SDK_BASE
        if target is None:
            unresolved.append(name)
            continue
        rows.append((MAIN_BASE + slot, target, name))
    for at in range(jump, jump + jump_size, 24):
        slot, info, _addend = struct.unpack_from("<QQq", update_image, at)
        if info & 0xFFFFFFFF != JUMP_SLOT:
            unresolved.append(None)
            continue
        name = symbol_name(update_image, entries, info >> 32)
        target = symbols.get(name)
        if target is not None:
            target += SDK_BASE
        if target is None:
            unresolved.append(name)
            continue
        rows.append((MAIN_BASE + slot, target, name))
    print("reloc types:", {hex(k): v for k, v in counts.items()})

    lines = [
        "/* Generated by tools/gen_guest_relocs.py - do not edit.",
        " *",
        " * The records the repacker dropped from the mapped guest image: the ABS64",
        " * slots for __cxa_pure_virtual, rtld's __rel_* pointers and every JUMP_SLOT",
        " * import of the main module.  Both fields are merged-image offsets; the",
        " * loader adds the random base. */",
        "#ifndef D3_GUEST_RELOCS_H",
        "#define D3_GUEST_RELOCS_H",
        "#include <stdint.h>",
        "typedef struct { uint32_t slot; uint32_t target; const char *name; } GuestReloc;",
        "static const GuestReloc g_guest_relocs[] = {",
    ]
    for slot, target, name in rows:
        lines.append(f'    {{0x{slot:08x}u, 0x{target:08x}u, "{name}"}},')
    lines += [
        "};",
        "#define D3_GUEST_RELOC_COUNT (sizeof g_guest_relocs / sizeof g_guest_relocs[0])",
        "#endif",
    ]
    Path(path_out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {path_out}: {len(rows)} records, {len(unresolved)} unresolved")
    if unresolved:
        print("unresolved:", sorted(set(n for n in unresolved if n)))
    return rows

def probe():
    base_image = image_of(BASE_MAIN)
    entries = dynamic_tables(base_image)
    print("base main dynamic:", {k: hex(v) for k, v in sorted(entries.items())})
    rela = entries.get(7)
    size = entries.get(8)
    kinds = {}
    named = []
    for at in range(rela, rela + size, 24):
        offset, info, addend = struct.unpack_from("<QQq", base_image, at)
        kind = info & 0xFFFFFFFF
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind != RELATIVE:
            named.append((kind, offset, symbol_name(base_image, entries, info >> 32)))
    print("base main RELA types:", {hex(k): v for k, v in kinds.items()})
    jmprel = entries.get(23)
    jumps = []
    for at in range(jmprel, jmprel + 0x2000, 24):
        offset, info, _addend = struct.unpack_from("<QQq", base_image, at)
        if info & 0xFFFFFFFF == JUMP_SLOT and offset < len(base_image):
            jumps.append((offset, symbol_name(base_image, entries, info >> 32)))
        elif jumps:
            break
    print(f"base main JUMP_SLOT: {len(jumps)}")
    update_image = image_of(UPDATE_MAIN)
    print("update main image:", hex(len(update_image)))
    for kind, label in ((RELATIVE, "RELATIVE"), (ABS64, "ABS64"), (GLOB_DAT, "GLOB_DAT"), (JUMP_SLOT, "JUMP_SLOT")):
        runs = find_relocation_runs(update_image, kind)
        best = max(runs, key=lambda r: r[1]) if runs else None
        print(f"  update {label}: best run {best if best is None else (hex(best[0]), best[1])}")
    return base_image, entries, named, jumps


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--emit", default=None)
    args = parser.parse_args()
    if args.emit:
        emit(args.emit)
    else:
        probe()
