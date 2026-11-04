#!/usr/bin/env python3
"""Print the host range that backs guest address 0 (g_mem) and nearby ranges."""
from __future__ import annotations

import sys
import time

import frida

JS = r"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x17AEF20).readPointer();
const r = Process.findRangeByAddress(gmem);
send({gmem: gmem.toString(), range: r ? {base: r.base.toString(), size: r.size, protection: r.protection} : null});
let count = 0;
for (const x of Process.enumerateRanges('rw-')) {
  if (x.base.compare(gmem) >= 0 && x.base.compare(gmem.add(0x200000000)) < 0) {
    send({near: {base: x.base.toString(), size: x.size, protection: x.protection}});
    if (++count > 20) break;
  }
}
"""


def main() -> None:
    session = frida.get_local_device().attach(int(sys.argv[1]))
    script = session.create_script(JS)
    script.on("message", lambda m, d: print(m.get("payload", m), flush=True))
    script.load()
    time.sleep(1)
    session.detach()


if __name__ == "__main__":
    main()
