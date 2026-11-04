#!/usr/bin/env python3
"""Canary test: does the guest copy a HID state value into its own memory?

Writes a unique value into the runtime's HID input state (pad buttons or the
mouse position/buttons) under the runtime's input lock, waits a few samples,
then scans writable guest memory for that value. A hit outside the shared
memory means the guest consumed the state and stored it somewhere; no hit in
a window where the same technique finds the pad canary means it did not.

Only reads and writes guest memory; it never sends UI input.

Usage:
  python tools/d3-re/hid_canary.py --pid <pid> --kind pad --seconds 0.5
  python tools/d3-re/hid_canary.py --pid <pid> --kind mouse --seconds 0.5
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import frida

JS = r"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase() === '01001b300b9be000.exe');
const base = exe.base;
const gm = base.add(0x17AEF20).readPointer();
const pm_lock = new NativeFunction(base.add(0x5FAD0), 'void', ['pointer']);
const pm_unlock = new NativeFunction(base.add(0x5FAE0), 'void', ['pointer']);
const hle = base.add(0xCEC6D0).readPointer();

function withLock(fn) {
  const lock = hle.add(0x2C8DC8);
  pm_lock(lock);
  try { return fn(); } finally { pm_unlock(lock); }
}
function padButtons(v) {
  return withLock(() => { if (v === null) return hle.add(0x2C89E0).readU64().toString();
                          hle.add(0x2C89E0).writeU64(uint64(v)); return 'set'; });
}
function mouseState(v) {
  const m = hle.add(0x2C8DA4);
  return withLock(() => {
    if (v === null) return m.readByteArray(0x20);
    m.add(0).writeS32(v.x); m.add(4).writeS32(v.y);
    m.add(0x18).writeU32(v.buttons); m.add(0x1C).writeS32(1);
    return 'set';
  });
}
function scanHex(hex) {
  const ranges = Process.enumerateRanges('rw-');
  const gmem = parseInt(gm.toString(), 16);
  const pat = hex;
  const hits = [];
  let scanned = 0;
  const started = Date.now();
  for (const r of ranges) {
    const start = parseInt(r.base.toString(), 16);
    if (start + r.size <= gmem) continue;
    if (start < gmem) continue;                 /* guest addresses only */
    if (Date.now() - started > 25000) break;
    if (r.size > 0x40000000) continue;          /* skip implausibly large spans */
    try {
      const found = Memory.scanSync(r.base, r.size, pat);
      for (const f of found) hits.push((parseInt(f.address.toString(), 16) - gmem).toString());
      if (found.length) scanned += 0;
      scanned += r.size;
    } catch (e) {}
    if (hits.length >= 32) break;
  }
  return { hits, scanned, elapsed_ms: Date.now() - started };
}
rpc.exports = {
  gmem: () => gm.toString(),
  pad: padButtons,
  mouse: mouseState,
  scan: scanHex,
  shm: () => {
    const obj = hle.add(0x2C8DD8).readPointer();
    return { gaddr: obj.add(0x48).readU64().toString(), gsize: obj.add(0x50).readU64().toString() };
  },
  base: () => ({ exe: base.toString(), code: Process.getModuleByName('01001B300B9BE000_code.dll').base.toString() })
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--kind", choices=["pad", "mouse"], required=True)
    ap.add_argument("--seconds", type=float, default=0.5)
    ap.add_argument("--out", type=str)
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync
    result = {"pid": args.pid, "kind": args.kind, "gmem": api.gmem(), "second_passes": []}

    if args.kind == "pad":
        # A 64-bit marker in bits the runtime passes through unchanged: A (bit 0) plus high bits.
        marker = 0x00000000ABC00001
        before = api.pad(None)
        api.pad(hex(marker))
        time.sleep(args.seconds)
        pattern = " ".join("%02x" % b for b in marker.to_bytes(8, "little"))
        scan = api.scan(pattern)
        api.pad('0x0')
        result.update({"before": before, "marker": hex(marker), "scan": scan, "shm": api.shm()})
    else:
        state = {"x": 0x0A0B0C0D, "y": 0x0D0C0B0A, "buttons": 0xC0DE0000 | 1}
        before = bytes(api.mouse(None)).hex()
        api.mouse(state)
        time.sleep(args.seconds)
        xhit = api.scan(" ".join("%02x" % b for b in (0x0A0B0C0D).to_bytes(4, "little")))
        yhit = api.scan(" ".join("%02x" % b for b in (0x0D0C0B0A).to_bytes(4, "little")))
        api.mouse({"x": 0, "y": 0, "buttons": 0})
        result.update({"before": before, "x_scan": xhit, "y_scan": yhit, "shm": api.shm()})

    print(json.dumps(result, indent=2)[:4000])
    if args.out:
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    session.detach()


if __name__ == "__main__":
    main()
