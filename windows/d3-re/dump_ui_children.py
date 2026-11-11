#!/usr/bin/env python3
"""Dump the child vectors of one live UI object.

UI objects place their screen rect at +0xd8 (x,y) and +0xf0 (w,h) in the
1280x720 virtual screen. Candidate child containers are pointer/size pairs at
+0x20/+0x28, +0x60/+0x70, +0x78/+0x80 and +0x88. This reads each candidate and
prints the objects it points to with their rect and name hash.

Usage:
  python windows/d3-re/dump_ui_children.py --pid 28080 --obj 5879782560
"""
from __future__ import annotations

import argparse
import json

import frida

JS = r"""
const P = PAYLOAD;
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x17AEF20).readPointer();
function u64(a) { return Number(gmem.add(a).readU64()); }
function f32(a) { return gmem.add(a).readFloat(); }
function rect(obj) {
  return [f32(obj + 0xe0), f32(obj + 0xe4), f32(obj + 0xe8), f32(obj + 0xec)];
}
try {
  const obj = P.obj;
  const out = {obj, vt: u64(obj).toString(16), hash: gmem.add(obj + 0x30).readU64().toString(), rect: rect(obj), lists: []};
  for (const [name, ptrOff, endOff] of [['a', 0x20, 0x28], ['b', 0x60, 0x78], ['c', 0x78, 0x80], ['d', 0x88, 0x90]]) {
    const begin = u64(obj + ptrOff), end = u64(obj + endOff);
    const count = end > begin && (end - begin) < 0x10000 ? (end - begin) / 8 : 0;
    const rec = {name, begin, end, count, items: []};
    if (count > 0 && count < 2000) {
      for (let i = 0; i < count; i++) {
        const child = u64(begin + i * 8);
        if (!child) continue;
        const item = {i, obj: child, vt: null, hash: null, rect: null};
        try {
          item.vt = u64(child).toString(16);
          item.hash = gmem.add(child + 0x30).readU64().toString();
          item.rect = rect(child);
        } catch (e) { item.error = e.message; }
        rec.items.push(item);
      }
    }
    out.lists.push(rec);
  }
  send(out);
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps({"obj": args.obj})))

    def on_message(message, data):
        p = message.get("payload", {})
        print(json.dumps(p, ensure_ascii=False), flush=True)
        session.detach()

    script.on("message", on_message)
    script.load()


if __name__ == "__main__":
    main()
