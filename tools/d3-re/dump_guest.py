"""Dump a guest address range to a local file through the runtime's g_mem base.

Read-only.  Uses tools/d3-re/version.py for the module lookup and build check.

Usage:
  python tools/d3-re/dump_guest.py --pid <pid> --addr 0x97DCF88 --size 0x380 --out out/windows/kbm/table.bin
"""
from __future__ import annotations

import argparse
from pathlib import Path

import frida

import version

JS = version.js_consts() + r"""
rpc.exports = {
  read(guest, size) {
    const bytes = new Uint8Array(gm.add(ptr(guest)).readByteArray(size));
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return bin;
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--addr", required=True, type=lambda s: int(s, 0))
    ap.add_argument("--size", required=True, type=lambda s: int(s, 0))
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    raw = script.exports_sync.read(args.addr, args.size)
    session.detach()
    data = raw.encode("latin-1")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"{args.addr:#x} + {args.size:#x} -> {args.out} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
