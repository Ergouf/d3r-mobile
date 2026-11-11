#!/usr/bin/env python3
"""Disassemble live guest code read through g_mem from the running game.

Guest code differs from the fixed ELF, so disassembly must come from the
installed runtime's own memory. Read-only: one attach, no guest calls.

Usage:
  python windows/d3-re/dis_guest.py --pid 6992 --at 0x8419140 --count 40
  python windows/d3-re/dis_guest.py --pid 6992 --at 0x8419140,0x8419170 --before 4
"""
from __future__ import annotations

import argparse

import frida
from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs

import version

JS = version.js_consts() + r"""
rpc.exports = {
  read(guest, size) {
    return Array.from(new Uint8Array(gm.add(ptr(guest)).readByteArray(size)));
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--at", required=True, type=lambda s: [int(x, 0) for x in s.split(",")])
    ap.add_argument("--count", type=int, default=32)
    ap.add_argument("--before", type=int, default=0)
    args = ap.parse_args()
    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        for addr in args.at:
            start = addr - args.before * 4
            size = (args.count + args.before) * 4
            data = bytes(script.exports_sync.read(start, size))
            print(f"=== {addr:#x} ===")
            for insn in md.disasm(data, start):
                mark = ">>" if insn.address == addr else "  "
                print(f"{mark}{insn.address:#010x}: {insn.mnemonic:<8}{insn.op_str}")
    finally:
        session.detach()


if __name__ == "__main__":
    main()
