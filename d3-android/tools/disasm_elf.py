"""Disassemble an AArch64 ELF virtual-address range without loading it.

Run with Python -I; requires capstone and pyelftools.
"""

import argparse
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, Cs
from elftools.elf.elffile import ELFFile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("start", type=lambda value: int(value, 0))
    parser.add_argument("--bytes", type=lambda value: int(value, 0), default=256)
    args = parser.parse_args()
    if args.start < 0 or not 0 < args.bytes <= 1024 * 1024:
        parser.error("Invalid range (maximum 1 MiB)")

    with args.elf.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.header["e_machine"] != "EM_AARCH64":
            parser.error("Expected an AArch64 ELF")
        for segment in elf.iter_segments():
            base = segment["p_vaddr"]
            end = base + segment["p_filesz"]
            if segment["p_type"] == "PT_LOAD" and base <= args.start < end:
                length = min(args.bytes, end - args.start)
                stream.seek(segment["p_offset"] + args.start - base)
                code = stream.read(length)
                break
        else:
            parser.error("Address is not in a file-backed PT_LOAD segment")

    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for instruction in decoder.disasm(code, args.start):
        print(f"{instruction.address:08x}: {instruction.bytes.hex():8s}  "
              f"{instruction.mnemonic:8s} {instruction.op_str}")


if __name__ == "__main__":
    main()
