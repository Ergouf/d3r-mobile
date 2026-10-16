"""Recover the generated command-name table from the preserved host ELF as data.

The struct layouts are evidenced by the recovered service C and AArch64 ABI.
Run with Python -I; requires pyelftools. Does not execute the ELF.
"""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile


INTERFACES = {
    "NONE": 0, "SM": 1, "APPLET_OE": 2, "APPLICATION_PROXY": 3,
    "APPLICATION_FUNCTIONS": 4, "DEBUG_FUNCTIONS": 5, "PCTL": 6,
    "AOC": 7, "FSP_SRV": 8, "LM": 9, "LOGGER": 10, "APM": 11,
    "COMMON_STATE_GETTER": 12, "SELF_CONTROLLER": 13, "WINDOW_CONTROLLER": 14,
    "AUDIO_CONTROLLER": 15, "DISPLAY_CONTROLLER": 16, "PROCESS_WINDING_CONTROLLER": 17,
    "LIBRARY_APPLET_CREATOR": 18, "LIBRARY_APPLET_ACCESSOR": 19,
    "LIBRARY_APPLET_SELF_ACCESSOR": 20, "STORAGE": 21,
}


def recover(path: Path) -> list:
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.header["e_machine"] != "EM_AARCH64" or not elf.little_endian:
            raise ValueError("Expected little-endian AArch64 ELF")
        loads = [segment for segment in elf.iter_segments() if segment["p_type"] == "PT_LOAD"]
        relatives = {
            relocation["r_offset"]: relocation["r_addend"]
            for relocation in elf.get_section_by_name(".rela.dyn").iter_relocations()
            if relocation["r_info_type"] == 1027
        }

        def read(address: int, count: int) -> bytes:
            for segment in loads:
                offset = address - segment["p_vaddr"]
                if 0 <= offset and offset + count <= segment["p_filesz"]:
                    stream.seek(segment["p_offset"] + offset)
                    return stream.read(count)
            raise ValueError(f"Address range outside ELF: {address:#x}+{count:#x}")

        def pointer(address: int) -> int:
            return relatives[address] if address in relatives else struct.unpack("<Q", read(address, 8))[0]

        def string(address: int) -> str:
            value = bytearray()
            for index in range(1024):
                byte = read(address + index, 1)[0]
                if byte == 0:
                    return value.decode("ascii")
                if not 0x20 <= byte <= 0x7e:
                    raise ValueError("Unexpected command-name encoding")
                value.append(byte)
            raise ValueError("Unterminated command name")

        symbols = elf.get_section_by_name(".symtab")
        table = next(symbol for symbol in symbols.iter_symbols() if symbol.name == "d3_command_sets")
        if table["st_size"] % 32 or table["st_size"] > 32 * 128:
            raise ValueError("Unexpected d3_command_sets layout")
        sets = []
        for offset in range(0, table["st_size"], 32):
            address = table["st_value"] + offset
            iface = struct.unpack("<I", read(address, 4))[0]
            name = string(pointer(address + 8))
            commands = pointer(address + 16)
            count = struct.unpack("<I", read(address + 24, 4))[0]
            if not re.fullmatch(r"I[A-Za-z0-9_]+", name) or count > 1024:
                raise ValueError("Unexpected command set")
            entries = []
            for index in range(count):
                entry = commands + index * 16
                command = struct.unpack("<I", read(entry, 4))[0]
                entries.append((command, string(pointer(entry + 8))))
            sets.append((iface, name, entries))
        return sets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sets = recover(args.elf)
    with args.elf.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    lines = [
        "/* Recovered from the preserved host ELF; not guessed command names. */",
        f"/* Source SHA-256: {checksum} */",
        "#ifndef D3_SERVICE_NAMES_H", "#define D3_SERVICE_NAMES_H",
        "#include <stddef.h>", "#include <stdint.h>", "", "enum {",
    ]
    lines.extend(f"    D3_IF_{name} = {value}," for name, value in INTERFACES.items())
    lines.extend([
        "};", "", "typedef struct { uint32_t command; const char *name; } d3_command_name;",
        "typedef struct { int iface; const char *name; const d3_command_name *commands; uint32_t count; } d3_command_set;", "",
    ])
    for _, name, entries in sets:
        lines.append(f"static const d3_command_name d3_commands_{name}[] = {{")
        lines.extend(f"    {{{command}u, {json.dumps(text)}}}," for command, text in entries)
        if not entries:
            lines.append("    {0, NULL},")
        lines.extend(["};", ""])
    lines.append("static const d3_command_set d3_command_sets[] = {")
    for iface, name, entries in sets:
        lines.append(f"    {{{iface}, {json.dumps(name)}, d3_commands_{name}, {len(entries)}}},")
    lines.extend(["};", "#define D3_COMMAND_SET_COUNT (sizeof d3_command_sets / sizeof d3_command_sets[0])", "#endif", ""])
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
    print(f"Recovered {len(sets)} interfaces, {sum(len(entries) for _, _, entries in sets)} commands")


if __name__ == "__main__":
    main()
