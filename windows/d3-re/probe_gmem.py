#!/usr/bin/env python3
"""Read a few guest addresses through the runtime's g_mem pointer (debug helper)."""
from __future__ import annotations

import json
import sys

import frida

JS = r"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
send({step: 'exe', base: exe ? exe.base.toString() : null});
const gmem = exe.base.add(0x17AEF20).readPointer();
send({step: 'gmem', gmem: gmem.toString()});
for (const a of [0x914f840, 0x8dcf212, 0x8005000, 0x987bf20]) {
  try {
    const bytes = new Uint8Array(gmem.add(a).readByteArray(16));
    send({step: 'read', addr: a, bytes: Array.from(bytes)});
  } catch (e) { send({step: 'read', addr: a, error: e.message}); }
}
const p1 = gmem.add(0x914f840).readU64();
send({step: 'p1', p1: p1.toString()});
if (p1) {
  for (const off of [0, 8, 0x10, 0x18]) {
    try { send({step: 'p1mem', off, v: gmem.add(p1 + off).readU64().toString()}); }
    catch (e) { send({step: 'p1mem', off, error: e.message}); }
  }
}
"""


def main() -> None:
    pid = int(sys.argv[1])
    session = frida.get_local_device().attach(pid)
    script = session.create_script(JS)

    def on_message(message, data):
        print(message.get("payload", message), flush=True)

    script.on("message", on_message)
    script.load()
    import time
    time.sleep(2)
    session.detach()


if __name__ == "__main__":
    main()
