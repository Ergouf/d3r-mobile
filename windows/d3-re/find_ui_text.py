#!/usr/bin/env python3
"""Find UI objects that own a visible localized string.

Scans the game's readable/writable memory for the UTF-8 or UTF-16LE bytes of a
string (default: 继续), then looks for pointers to those addresses in every UI
registry object's first 0x200 bytes. That maps a visible label back to its
widget object.

Usage:
  python windows/d3-re/find_ui_text.py --pid 28080 --text 继续
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
function u32(a) { return gmem.add(a).readU32(); }
try {
  // find the string in memory
  const matches = [];
  for (const pat of P.patterns) {
    if (matches.length >= 24) break;
    for (const r of Process.enumerateRanges('rw-')) {
      if (matches.length >= 24) break;
      try {
        const found = Memory.scanSync(r.base, r.size, pat);
        for (const m of found) {
          if (matches.length >= 24) break;
          matches.push(m.address);
        }
      } catch (e) {}
    }
  }
  const guestMatches = matches.map(a => a.sub(gmem));
  const out = {matches: matches.map(a => a.toString()), guestMatches: guestMatches.map(a => a.toString()), objects: []};
  if (!guestMatches.length) { send(out); } else {
    const p1 = u64(0x914f840);
    const p2 = u64(p1 + 0x10);
    const p3 = u64(p2 + 0xb80);
    const map = u64(p3);
    const mask = u32(map), count = u32(map + 4), buckets = u64(map + 0x10);
    for (let b = 0; b <= mask; b++) {
      let node = u64(buckets + b * 8);
      let guard = 0;
      while (node && guard++ < 1000) {
        const obj = u64(node + 0x10);
        node = u64(node);
        if (!obj) continue;
        for (let off = 0; off < 0x200; off += 8) {
          let v;
          try { v = u64(obj + off); } catch (e) { break; }
          for (const m of guestMatches) {
            const ma = Number(m);
            if (v === ma || (v > ma - 0x80 && v < ma + 0x100)) {
              out.objects.push({obj, off, value: v, match: ma, key: gmem.add(obj + 0x30).readU64().toString()});
            }
          }
        }
      }
    }
  }
  send(out);
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--text", default="继续")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    patterns = [
        args.text.encode("utf-8").hex(),
        args.text.encode("utf-16le").hex(),
        args.text.encode("utf-16be").hex(),
    ]
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps({"patterns": patterns})))

    def on_message(message, data):
        p = message.get("payload", {})
        if args.json:
            print(json.dumps(p, ensure_ascii=False), flush=True)
        else:
            print(f"string matches: {len(p.get('matches', []))}", p.get("matches", [])[:10], flush=True)
            for o in p.get("objects", []):
                print(o, flush=True)
        session.detach()

    script.on("message", on_message)
    script.load()


if __name__ == "__main__":
    main()
