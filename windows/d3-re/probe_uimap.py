#!/usr/bin/env python3
"""Read the UI registry map header through g_mem (debug helper)."""
from __future__ import annotations

import sys
import time

import frida

from version import RVA

JS = (
    r"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x%X).readPointer();
"""
    % RVA["g_mem"]
) + r"""
function u64(a) { return gmem.add(a).readU64(); }
function u32(a) { return gmem.add(a).readU32(); }
function send64(name, a) { try { send({step: name, addr: a.toString(), v: u64(a).toString()}); } catch (e) { send({step: name, addr: a.toString(), error: e.message}); } }
const p1 = u64(0x914f840);
send({step: 'p1', v: p1.toString()});
const p2 = u64(p1 + 0x10);
send({step: 'p2', v: p2.toString()});
const p3 = u64(p2 + 0xb80);
send({step: 'p3', v: p3.toString(), hex: p3.toString(16)});
const map = u64(p3);
send({step: 'map', v: map.toString(), hex: map.toString(16)});
for (const off of [0, 4, 8, 0x10, 0x18]) {
  try { send({step: 'map+' + off, v: gmem.add(map + off).readU64().toString()}); }
  catch (e) { send({step: 'map+' + off, error: e.message}); }
}
const mask = u32(map), count = u32(map + 4), buckets = u64(map + 0x10);
send({step: 'header', mask, count, buckets: buckets.toString()});
let node = u64(buckets);
for (let i = 0; i < 6 && node; i++) {
  try {
    send({step: 'node' + i, node: node.toString(), next: u64(node).toString(),
          key: u64(node + 8).toString(), obj: u64(node + 0x10).toString(),
          vt: u64(u64(node + 0x10)).toString()});
  } catch (e) { send({step: 'node' + i, node: node.toString(), error: e.message}); break; }
  node = u64(node);
}
"""


def main() -> None:
    session = frida.get_local_device().attach(int(sys.argv[1]))
    script = session.create_script(JS)
    script.on("message", lambda m, d: print(m.get("payload", m), flush=True))
    script.load()
    time.sleep(2)
    session.detach()


if __name__ == "__main__":
    main()
