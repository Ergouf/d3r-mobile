#!/usr/bin/env python3
"""Build a loadable AArch64 ELF from a decompressed Diablo III main NSO image.

hactool --uncompressed is the supported way to produce the input image:

  hactool -t nso --uncompressed=main.bin main.nso0

The image keeps the NSO0 header, and each segment's file offset is not its
memory offset (text file offset is normally 0x100).  The ELF must place each
segment at the *memory* offset, otherwise Ghidra sees every address shifted by
0x100 and every string reference points at the wrong bytes.

This wrapper only reads the game file; its output is analysis scratch data and
belongs under out/windows/kbm/.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

PAGE = 0x1000


def align(value: int, alignment: int = PAGE) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def read_header(image: bytes) -> dict:
    if image[:4] != b"NSO0":
        raise SystemExit("input is not an NSO0 image (expected hactool --uncompressed output)")
    if len(image) < 0x100:
        raise SystemExit("input is shorter than the NSO header")
    flags = struct.unpack_from("<I", image, 0x0C)[0]
    text_file, text_mem, text_size = struct.unpack_from("<III", image, 0x10)
    mod_name = struct.unpack_from("<I", image, 0x1C)[0]
    ro_file, ro_mem, ro_size = struct.unpack_from("<III", image, 0x20)
    # The Switch NSO header has one reserved word at 0x2C before the data
    # segment's file/memory/size fields (0x30/0x34/0x38); bss_size is 0x3C.
    data_file, data_mem, data_size = struct.unpack_from("<III", image, 0x30)
    bss_size = struct.unpack_from("<I", image, 0x3C)[0]
    return {
        "flags": flags,
        "text": (text_file, text_mem, text_size),
        "ro": (ro_file, ro_mem, ro_size),
        "data": (data_file, data_mem, data_size),
        "bss_size": bss_size,
        "mod_name": mod_name,
    }


def build(image: bytes, out: Path) -> None:
    h = read_header(image)
    segments = []
    for name in ("text", "ro", "data"):
        file_off, mem_off, size = h[name]
        if file_off + size > len(image):
            raise SystemExit(f"{name} segment lies outside the image: {file_off:#x}+{size:#x} > {len(image):#x}")
        segments.append((name, file_off, mem_off, size))
    bss_mem = h["data"][1] + h["data"][2]
    bss_size = h["bss_size"]

    # Lay the segments out in the ELF file at page-aligned offsets, keeping the
    # program headers' virtual addresses equal to the NSO memory offsets.
    file_cursor = PAGE
    layout = []
    for name, file_off, mem_off, size in segments:
        file_cursor = align(file_cursor)
        layout.append((name, file_off, mem_off, size, file_cursor))
        file_cursor += size
    shstr = b"\0.text\0.rodata\0.data\0.bss\0.shstrtab\0"
    shstr_file = align(file_cursor)
    total = shstr_file + len(shstr)
    buf = bytearray(total)

    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8)
    phoff = 64
    phnum = 4
    shoff = phoff + 56 * phnum
    shnum = 6
    struct.pack_into(
        "<16sHHIQQQIHHHHHH", buf, 0, ident, 2, 183, 1, 0, phoff, shoff, 0,
        64, 56, phnum, 64, shnum, 5,
    )

    for name, file_off, mem_off, size, elf_off in layout:
        buf[elf_off:elf_off + size] = image[file_off:file_off + size]

    buf[shstr_file:shstr_file + len(shstr)] = shstr

    phdrs = []
    for name, file_off, mem_off, size, elf_off in layout:
        flags = {"text": 5, "ro": 4, "data": 6}[name]
        phdrs.append((1, flags, elf_off, mem_off, mem_off, size, size, PAGE))
    phdrs.append((1, 6, 0, bss_mem, bss_mem, 0, bss_size, PAGE))
    for i, ph in enumerate(phdrs):
        struct.pack_into("<IIQQQQQQ", buf, phoff + i * 56, *ph)

    def sh(name: int, typ: int, flags: int, addr: int, off: int, size: int,
           link: int = 0, info: int = 0, addralign: int = 1, entsize: int = 0) -> tuple:
        return (name, typ, flags, addr, off, size, link, info, addralign, entsize)

    sections = [
        sh(0, 0, 0, 0, 0, 0),
        sh(1, 1, 6, h["text"][1], layout[0][4], h["text"][2]),
        sh(7, 1, 2, h["ro"][1], layout[1][4], h["ro"][2]),
        sh(15, 1, 3, h["data"][1], layout[2][4], h["data"][2]),
        sh(21, 8, 3, bss_mem, 0, bss_size),
        sh(26, 3, 0, 0, shstr_file, len(shstr)),
    ]
    for i, section in enumerate(sections):
        struct.pack_into("<IIQQQQIIQQ", buf, shoff + i * 64, *section)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf)
    print(f"wrote {out} ({len(buf)} bytes)")
    for name, file_off, mem_off, size, elf_off in layout:
        print(f"{name:4s} file={file_off:#x} mem={mem_off:#x} size={size:#x} elf_off={elf_off:#x}")
    print(f"bss  mem={bss_mem:#x} size={bss_size:#x}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="decompressed main image (hactool --uncompressed)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.image.read_bytes(), args.out)


if __name__ == "__main__":
    main()
