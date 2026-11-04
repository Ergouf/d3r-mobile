#!/usr/bin/env python3
"""Scan live UI objects for valid screen rects.

UI objects store their screen rect at +0xd8 (x, y) and +0xf0 (w, h) in the
1280x720 virtual screen. This enumerates the whole registry and prints the
objects whose rect falls inside an optional region, sorted by y then x.

Usage:
  python tools/d3-re/scan_ui_rects.py --pid 28080 --region 68,243,468,553
"""
from __future__ import annotations

import argparse
import json
import struct

import frida

JS = r"""
const P = PAYLOAD;
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x17AEF20).readPointer();
function u64(a) { return Number(gmem.add(a).readU64()); }
function u32(a) { return gmem.add(a).readU32(); }
function f32(a) { return gmem.add(a).readFloat(); }
try {
  const p1 = u64(0x914f840);
  const p2 = u64(p1 + 0x10);
  const p3 = u64(p2 + 0xb80);
  const map = u64(p3);
  const mask = u32(map), count = u32(map + 4), buckets = u64(map + 0x10);
  const out = {count, items: []};
  for (let b = 0; b <= mask; b++) {
    let node = u64(buckets + b * 8);
    let guard = 0;
    while (node && guard++ < 1000) {
      const obj = u64(node + 0x10);
      const key = gmem.add(node + 8).readU64().toString();
      node = u64(node);
      if (!obj) continue;
      let x, y, w, h, vt;
      try {
        x = f32(obj + 0xe0); y = f32(obj + 0xe4); w = f32(obj + 0xe8); h = f32(obj + 0xec);
        vt = u64(obj).toString(16);
      } catch (e) { continue; }
      if (!(w > 0 && h > 0 && w < 4000 && h < 4000 && Math.abs(x) < 4000 && Math.abs(y) < 4000)) continue;
      if (P.region) {
        const [x1, y1, x2, y2] = P.region;
        if (x + w < x1 || x > x2 || y + h < y1 || y > y2) continue;
      }
      out.items.push({obj, key, vt, x, y, w, h});
    }
  }
  out.items.sort((a, b) => (a.y - b.y) || (a.x - b.x));
  send(out);
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--region", default=None, help="x1,y1,x2,y2")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    region = [float(v) for v in args.region.split(",")] if args.region else None
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps({"region": region})))

    def on_message(message, data):
        p = message.get("payload", {})
        if args.json:
            print(json.dumps(p, ensure_ascii=False), flush=True)
        else:
            print(f"objects with rects: {len(p.get('items', []))} (registry {p.get('count')})", flush=True)
            for it in p.get("items", []):
                print(f"obj={it['obj']:>11} vt={it['vt']:>8} key={it['key']:>20} "
                      f"rect=({it['x']:7.1f},{it['y']:7.1f}) {it['w']:7.1f}x{it['h']:6.1f}", flush=True)
        session.detach()

    script.on("message", on_message)
    script.load()


if __name__ == "__main__":
    main()
