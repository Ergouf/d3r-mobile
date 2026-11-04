"""Read several guest addresses in one attach and print bytes plus ASCII.

Read-only helper for following pointers out of engine tables.

Usage:
  python tools/d3-re/read_guest.py --pid <pid> --addr 0x8E24592 --size 0x40 [--addr ...]
"""
from __future__ import annotations

import argparse

import frida

import version

JS = version.js_consts() + r"""
rpc.exports = {
  read(guest, size) {
    const bytes = new Uint8Array(gm.add(ptr(guest)).readByteArray(size));
    return Array.from(bytes);
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--addr", action="append", required=True, type=lambda s: int(s, 0))
    ap.add_argument("--size", type=lambda s: int(s, 0), default=0x40)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    for addr in args.addr:
        try:
            data = bytes(script.exports_sync.read(addr, args.size))
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"{addr:#x}  error: {exc}")
            continue
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        print(f"{addr:#x}  {data.hex()}")
        print(f"          {text}")
    session.detach()


if __name__ == "__main__":
    main()
