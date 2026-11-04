#!/usr/bin/env python3
"""List a few UI registry entries through g_mem (minimal debug helper)."""
from __future__ import annotations

import json
import sys
import time

import frida

JS = r"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x17AEF20).readPointer();
function u64(a) { return Number(gmem.add(a).readU64()); }
function u32(a) { return gmem.add(a).readU32(); }
try {
  const p1 = u64(0x914f840);
  const p2 = u64(p1 + 0x10);
  const p3 = u64(p2 + 0xb80);
  const map = u64(p3);
  const mask = u32(map), count = u32(map + 4), buckets = u64(map + 0x10);
  const out = {p1, p2, p3, map, mask, count, buckets, entries: []};
  for (let b = 0; b < 8; b++) {
    let node = u64(buckets + b * 8);
    for (let k = 0; k < 8 && node; k++) {
      const key = u64(node + 8), obj = u64(node + 0x10);
      out.entries.push({b, k, node, key, obj, vt: u64(obj)});
      node = u64(node);
    }
  }
  send(out);
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    session = frida.get_local_device().attach(int(sys.argv[1]))
    script = session.create_script(JS)

    def on_message(message, data):
        print(json.dumps(message.get("payload", message), ensure_ascii=False), flush=True)
        session.detach()

    script.on("message", on_message)
    script.load()
    time.sleep(1)
    session.detach()


if __name__ == "__main__":
    main()
