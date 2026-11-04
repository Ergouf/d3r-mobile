#!/usr/bin/env python3
"""Find UI registry objects by their full path name (FNV-1a 64 of lowercase).

The UI object map keys are FNV-1a 64 hashes of the lowercased UI path, e.g.
`root.normallayer.consolemainmenu_main`. This tool builds candidate paths from
the runtime rodata, finds matching objects, and prints their first fields and a
raw qword/float window so their layout can be identified.

Usage:
  python tools/d3-re/find_ui_object.py --pid 28080 --prefix root.normallayer.consolemainmenu_main
  python tools/d3-re/find_ui_object.py --pid 28080 --name root.normallayer.consolemainmenu_main.layoutroot
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from pathlib import Path

import frida

from version import RVA, assert_installed

RODATA = Path("out/windows/kbm/b2/runtime_rodata.bin")
MASK64 = (1 << 64) - 1

JS = (
    r"""
const P = PAYLOAD;
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x%X).readPointer();
"""
    % RVA["g_mem"]
) + r"""
function u64(a) { return gmem.add(a).readU64(); }
function num(a) { return Number(u64(a)); }
try {
  const p1 = num(0x914f840);
  const p2 = num(p1 + 0x10);
  const p3 = num(p2 + 0xb80);
  const map = num(p3);
  const mask = gmem.add(map).readU32(), count = gmem.add(map + 4).readU32(), buckets = num(map + 0x10);
  const wanted = new Map(P.targets.map(h => [h, null]));
  for (let b = 0; b <= mask; b++) {
    let node = num(buckets + b * 8);
    let guard = 0;
    while (node && guard++ < 1000) {
      const key = u64(node + 8).toString();
      if (wanted.has(key)) wanted.set(key, num(node + 0x10));
      node = num(node);
    }
  }
  const out = {count, mask, objects: []};
  for (const [key, obj] of wanted) {
    if (!obj) { out.objects.push({key, found: false}); continue; }
    const rec = {key, found: true, obj: obj.toString(), vt: u64(obj).toString(), q: [], f: []};
    try {
      for (let o = 0; o < P.dump; o += 8) rec.q.push(u64(obj + o).toString());
      for (let o = 0; o < P.dump; o += 4) rec.f.push(gmem.add(obj + o).readFloat());
      const s = num(obj + 0x30);
      if (s) {
        try {
          const bytes = new Uint8Array(gmem.add(s).readByteArray(64));
          let str = '';
          for (let i = 0; i < bytes.length && bytes[i] >= 32 && bytes[i] < 127; i++) str += String.fromCharCode(bytes[i]);
          rec.string30 = str;
        } catch (e) {}
      }
    } catch (e) { rec.error = e.message; }
    out.objects.push(rec);
  }
  send(out);
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def fnv1a64(s: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in s:
        h ^= c
        h = (h * 0x100000001B3) & MASK64
    return h


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--name", action="append", default=[])
    ap.add_argument("--dump", type=lambda s: int(s, 0), default=0x100)
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--rodata", type=Path, default=RODATA)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    assert_installed()

    names: list[str] = list(args.name)
    if args.prefix:
        data = args.rodata.read_bytes()
        prefix = args.prefix.lower()
        for m in re.finditer(rb"[ -~]{4,240}", data):
            s = m.group().decode("latin1").lower()
            if s.startswith(prefix):
                names.append(s)
    names = sorted(set(n.lower() for n in names))[:args.max]
    if not names:
        print("no candidate names", file=sys.stderr)
        return
    targets = {format(fnv1a64(n.encode()), "d"): n for n in names}
    # JSON keys are decimal strings, as JS prints u64 decimal
    payload = {"targets": list(targets.keys()), "dump": args.dump}
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))
    finished = threading.Event()

    def on_message(message, data):
        p = message.get("payload", {})
        if args.json:
            for rec in p.get("objects", []):
                rec["name"] = targets.get(rec.get("key"), "?")
            print(json.dumps(p, ensure_ascii=False), flush=True)
            finished.set()
            return
        if p.get("error"):
            print(p, flush=True)
        else:
            print(f"registry count={p.get('count')} mask={p.get('mask')}", flush=True)
            for rec in p.get("objects", []):
                name = targets.get(rec.get("key"), "?")
                if not rec.get("found"):
                    print(f"MISS {name}", flush=True)
                    continue
                print(f"\n=== {name}\nobj={rec['obj']} vt={rec['vt']}", flush=True)
                if rec.get("string30"):
                    print(f"string30={rec['string30']!r}", flush=True)
                q = [int(x) for x in rec.get("q", [])]
                for i in range(0, len(q), 4):
                    print(f"  +{i*8:04x}: " + " ".join(f"{v & MASK64:016x}" for v in q[i:i+4]), flush=True)
                f = rec.get("f", [])
                for i in range(0, len(f), 8):
                    print(f"  f+{i*4:04x}: " + " ".join("nan" if v is None else f"{v: .4f}" for v in f[i:i+8]), flush=True)
        finished.set()

    script.on("message", on_message)
    try:
        script.load()
        if not finished.wait(12):
            raise TimeoutError("UI object query did not finish")
    finally:
        session.detach()


if __name__ == "__main__":
    main()
