#!/usr/bin/env python3
"""Dump the game's UI object registry from the live runtime.

`0x8337b70` inserts `(name_hash, object*)` into a hash map reached through the
global at guest `0x914f840`:

    P1 = *(u64*)0x914f840
    P2 = *(u64*)(P1 + 0x10)
    M  = *(u64*)(P2 + 0xb80)
    M+0x00 : bucket mask (u32)
    M+0x04 : entry count (u32)
    M+0x10 : bucket array (guest pointer)
    node   : +0x00 next, +0x08 key (u64), +0x10 value (object guest pointer)

The probe reads the map through `g_mem` and prints keys and object fields, so we
can match known UI names against the runtime registry.

Usage:
  python windows/d3-re/dump_ui_objects.py --pid 22876 --max 40
"""
from __future__ import annotations

import argparse
import json

import frida

G_MEM_OFFSET = 0x17AEF20
JS = r"""
const P = PAYLOAD;
try {
  const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
  if (!exe) throw new Error('runtime exe not found');
  const gmem = exe.base.add(P.g_mem).readPointer();
  function rd64(guest) { return Number(gmem.add(guest).readU64()); }
  function rd32(guest) { return gmem.add(guest).readU32(); }
  function rdptr(guest) { return gmem.add(guest).readPointer(); }
  const p1 = rd64(0x914f840);
  const p2 = p1 ? rd64(p1 + 0x10) : 0;
  const p3 = p2 ? rd64(p2 + 0xb80) : 0;
  const map = p3 ? rd64(p3) : 0;
  const out = {p1: p1.toString(), p2: p2.toString(), p3: p3.toString(), map: map.toString(), entries: 0, objects: []};
  if (map) {
    const mask = rd32(map);
    const count = rd32(map + 4);
    const buckets = rd64(map + 0x10);
    out.mask = mask;
    out.count = count;
    out.buckets = buckets.toString();
    const maxBuckets = Math.min(mask + 1, P.buckets || 64);
    for (let b = 0; b < maxBuckets; b++) {
      let node = rd64(buckets + b * 8);
      for (let k = 0; k < P.perBucket && node; k++) {
        const key = rd64(node + 8);
        const obj = rd64(node + 0x10);
        const rec = {bucket: b, key: key.toString(), obj: obj.toString()};
        try {
          rec.vt = rd64(obj).toString(16);
          rec.f30 = rd64(obj + 0x30).toString();
          rec.f38 = rd64(obj + 0x38).toString();
          rec.f40 = rd32(obj + 0x40);
          rec.f48 = rd64(obj + 0x48).toString();
          rec.f50 = rd64(obj + 0x50).toString();
          rec.f58 = rd64(obj + 0x58).toString();
          rec.f60 = rd64(obj + 0x60).toString();
          const s30 = rd64(obj + 0x30);
          if (s30) {
            const bytes = new Uint8Array(gmem.add(s30).readByteArray(96));
            let s = '';
            for (let i = 0; i < bytes.length && bytes[i] !== 0 && bytes[i] >= 32 && bytes[i] < 127; i++)
              s += String.fromCharCode(bytes[i]);
            rec.s30 = s;
          }
        } catch (e) { rec.err = e.message; }
        out.objects.push(rec);
        if (out.objects.length >= P.max) { b = maxBuckets; break; }
        node = rd64(node);
      }
    }
  }
  send(out);
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(
        JS.replace("PAYLOAD", json.dumps({"g_mem": G_MEM_OFFSET, "max": args.max, "buckets": 8, "perBucket": 8})))

    def on_message(message, data):
        payload = message.get("payload", {})
        if args.json:
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return
        if payload.get("event") == "progress":
            print(payload, flush=True)
            return
        print({k: v for k, v in payload.items() if k != "objects"}, flush=True)
        for obj in payload.get("objects", []):
            print(obj, flush=True)
        session.detach()

    script.on("message", on_message)
    script.load()


if __name__ == "__main__":
    main()
