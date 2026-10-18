"""List the call sites of a guest function (AArch64 direct BL) by virtual address.

The guest image has program headers only, so the scan walks PT_LOAD segments the
same way tools/dis_guest.py does.

Usage:
  py -3 tools/find_calls.py <guest.so> <target-vaddr> [...more targets]

Addresses are the guest image's own virtual addresses, i.e. the offsets the host
prints as "sdk+0x..." (the image is mapped at one bias).
"""

import struct
import sys


def load_segments(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:4] != b"\x7fELF":
        sys.exit("%s is not an ELF file" % path)
    (e_phoff,) = struct.unpack_from("<Q", data, 0x20)
    (e_phentsize,) = struct.unpack_from("<H", data, 0x36)
    (e_phnum,) = struct.unpack_from("<H", data, 0x38)
    segments = []
    for index in range(e_phnum):
        base = e_phoff + index * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz, _memsz, _align = struct.unpack_from(
            "<IIQQQQQQ", data, base
        )
        if p_type == 1 and p_filesz and p_flags & 1:  # PT_LOAD, executable
            segments.append((p_vaddr, p_filesz, p_offset))
    return data, segments


def main(argv):
    data, segments = load_segments(argv[0])
    targets = {int(value, 0) for value in argv[1:]}
    calls = {target: [] for target in targets}
    for p_vaddr, p_filesz, p_offset in segments:
        chunk = data[p_offset : p_offset + p_filesz]
        for offset in range(0, len(chunk) - 3, 4):
            word = struct.unpack_from("<I", chunk, offset)[0]
            if word & 0xFC000000 != 0x94000000:
                continue
            delta = word & 0x03FFFFFF
            if delta & 0x02000000:
                delta -= 0x04000000
            site = p_vaddr + offset
            if site + delta * 4 in targets:
                calls[site + delta * 4].append(site)
    for target in sorted(targets):
        print(f"=== calls to {target:#x} ===")
        for site in calls[target]:
            print(f"  {site:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
