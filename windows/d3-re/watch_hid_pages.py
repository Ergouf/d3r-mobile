#!/usr/bin/env python3
"""Sample who accesses a HID shared-memory page, with per-window one-shot arms.

The monitor is validated by `monitor_selftest.py`: with one read per arm it
reports exactly one callback and the read completes. Here each arm catches the
*first* access after it, records the instruction and thread that made it, then
re-arms after a randomized delay so the sampling is not locked to the runtime's
period. That gives a sample of first-accessors, not a complete trace: a page
that is only ever seen from the runtime does not prove the guest never reads
it, because accesses during the blind interval are missed.

RVA defaults come from `windows/d3-re/version.py`, which pins the installed
exe/code.dll hashes and stops on a mismatch.

Usage:
  python windows/d3-re/watch_hid_pages.py --pid <pid> --page 0x3000 --seconds 5
  python windows/d3-re/watch_hid_pages.py --pid <pid> --page 0x9000 --size 0x4000 --seconds 5
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import frida

import version

HOST_JS = version.js_consts() + r"""
const out = { windows: 0, callbacks: 0, by_from: {}, by_thread: {}, armed_ms: 0, blind_ms: 0,
              errors: [], stopped: false, host: null, page: null };
const code = Process.enumerateModules().find(m => m.name.toLowerCase() === '01001b300b9be000_code.dll');
function classify(addr) {
  const v = parseInt(addr, 16);
  const exeBase = parseInt(base.toString(), 16);
  const codeBase = parseInt(code.base.toString(), 16);
  if (v >= codeBase && v < codeBase + code.size) return 'guest:' + (v - codeBase).toString(16);
  if (v >= exeBase && v < exeBase + exe.size) return 'runtime:' + (v - exeBase).toString(16);
  return 'other:' + addr;
}
const hle = base.add(RVA.g_hle_ptr).readPointer();
const host = kshmem(hle.add(HLE.shm).readPointer());
out.host = host.toString();
const page = host.add(PAGE).and(ptr('0xfffffffffffff000'));
out.page = page.toString();
const ranges = [ { base: page, size: P_SIZE } ];
let armedAt = 0, blindAt = 0;
function delay() { return 1 + Math.floor(Math.random() * 16); }
function arm() {
  if (out.stopped) return;
  armedAt = Date.now();
  try {
    MemoryAccessMonitor.enable(ranges, {
      onAccess(d) {
        out.callbacks++;
        const key = classify(d.from.toString()) + ' ' + d.operation;
        out.by_from[key] = (out.by_from[key] || 0) + 1;
        const t = String(Process.getCurrentThreadId());
        out.by_thread[t] = (out.by_thread[t] || 0) + 1;
        out.armed_ms += Date.now() - armedAt;
        try { MemoryAccessMonitor.disable(); } catch (e) {}
        blindAt = Date.now();
        setTimeout(() => { out.windows++; out.blind_ms += Date.now() - blindAt; arm(); }, delay());
      }
    });
  } catch (e) { out.errors.push(e.message); }
}
setTimeout(arm, 50);
rpc.exports = {
  data: () => out,
  stop: () => { out.stopped = true; try { MemoryAccessMonitor.disable(); } catch (e) {} return out; }
};
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--page", type=lambda s: int(s, 0), default=0x3000)
    ap.add_argument("--size", type=lambda s: int(s, 0), default=0x1000)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if not 0.5 <= args.seconds <= 60:
        ap.error("seconds must be 0.5..60")
    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(HOST_JS.replace("PAGE", hex(args.page)).replace("P_SIZE", hex(args.size)))
    script.load()
    time.sleep(args.seconds)
    data = script.exports_sync.stop()
    session.detach()
    total = args.seconds * 1000
    result = {"pid": args.pid, "page": hex(args.page), "size": hex(args.size), "seconds": args.seconds,
              **data, "duty_cycle": round(data.get("armed_ms", 0) / total, 4) if total else None}
    text = json.dumps(result, indent=2)
    print(text[:4000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
