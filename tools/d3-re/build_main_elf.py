#!/usr/bin/env python3
"""Build a loadable AArch64 ELF from a decompressed Diablo III main NSO image.

hactool --uncompressed is the supported way to produce the input image:

  hactool -t nso --uncompressed=main.bin main.nso0

This wrapper exists because Ghidra imports an ELF with program headers far more
reliably than a raw NSO. It does not modify the game; the output is analysis
scratch data and belongs under out/windows/kbm/.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

PAGE = 0x1000
TEXT_MEM = 0
RO_MEM = 0xC73000
DATA_MEM = 0x1098000


def align(value: int, alignment: int = PAGE) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def build(image: bytes, out: Path) -> None:
    text_size = 0xC72B90
    ro_size = 0x4249C4
    data_size = 0xC4A14
    bss_size = 0x94A000
    if len(image) < DATA_MEM + data_size:
        raise SystemExit(f"image is too small: {len(image):#x}")

    text_file = 0x1000
    ro_file = align(text_file + text_size)
    data_file = align(ro_file + ro_size)
    shstr = b"\0.text\0.rodata\0.data\0.bss\0.shstrtab\0"
    shstr_file = align(data_file + data_size)
    total = shstr_file + len(shstr)
    buf = bytearray(total)

    # ELF64 header, little endian, ET_EXEC, AArch64.
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8)
    phoff = 64
    phnum = 4
    shoff = phoff + 56 * phnum
    shnum = 6
    struct.pack_into(
        "<16sHHIQQQIHHHHHH", buf, 0, ident, 2, 183, 1, 0, phoff, shoff, 0,
        64, 56, phnum, 64, shnum, 5,
    )
    buf[text_file:text_file + text_size] = image[:text_size]
    buf[ro_file:ro_file + ro_size] = image[RO_MEM:RO_MEM + ro_size]
    buf[data_file:data_file + data_size] = image[DATA_MEM:DATA_MEM + data_size]
    buf[shstr_file:shstr_file + len(shstr)] = shstr

    phdrs = [
        (1, 5, text_file, TEXT_MEM, TEXT_MEM, text_size, text_size, PAGE),
        (1, 4, ro_file, RO_MEM, RO_MEM, ro_size, ro_size, PAGE),
        (1, 6, data_file, DATA_MEM, DATA_MEM, data_size, data_size, PAGE),
        (1, 6, 0, DATA_MEM + data_size, DATA_MEM + data_size, 0, bss_size, PAGE),
    ]
    for i, ph in enumerate(phdrs):
        struct.pack_into("<IIQQQQQQ", buf, phoff + i * 56, *ph)

    def sh(name: int, typ: int, flags: int, addr: int, off: int, size: int,
           link: int = 0, info: int = 0, addralign: int = 1, entsize: int = 0) -> tuple:
        return (name, typ, flags, addr, off, size, link, info, addralign, entsize)

    sections = [
        sh(0, 0, 0, 0, 0, 0),
        sh(1, 1, 6, TEXT_MEM, text_file, text_size),
        sh(7, 1, 2, RO_MEM, ro_file, ro_size),
        sh(15, 1, 3, DATA_MEM, data_file, data_size),
        sh(21, 8, 3, DATA_MEM + data_size, 0, bss_size),
        sh(26, 3, 0, 0, shstr_file, len(shstr)),
    ]
    for i, section in enumerate(sections):
        struct.pack_into("<IIQQQQIIQQ", buf, shoff + i * 64, *section)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf)
    print(f"wrote {out} ({len(buf)} bytes)")
    print(f"text={TEXT_MEM:#x}+{text_size:#x} ro={RO_MEM:#x}+{ro_size:#x} "
          f"data={DATA_MEM:#x}+{data_size:#x} bss={DATA_MEM + data_size:#x}+{bss_size:#x}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="decompressed main image (hactool --uncompressed)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.image.read_bytes(), args.out)


if __name__ == "__main__":
    main()
