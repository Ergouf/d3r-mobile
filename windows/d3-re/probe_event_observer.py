"""Read-only observer for the engine's input event dispatch.

GuestFn has the host ABI void(CPU* c, u64 entry): the second argument is the
actual guest entry PC, so this probe filters on args[1] instead of guessing
from LR.  Events are built by the input manager caller (0x82B9500..0x82B9590)
and dispatched through 0x82B80C0(event*, player, flag); the event struct holds
type at +0, player at +0x28 and the logical bit index at +0x2C.

The probe records, for every dispatch: entry PC, guest LR, host thread, event
type/player/bit, the raw 0x48 event bytes, and the per-player old/current
logical words (R + p*0x10C + 0x338 / +0x370).  It writes nothing except the
pad state used to produce a diagnostic positive through the runtime's own
sampler.

Usage:
  python windows/d3-re/probe_event_observer.py --pid <pid> --out out/windows/kbm/events.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida

import version

JS = version.js_consts() + r"""
const hle = base.add(RVA.g_hle_ptr).readPointer();
const TARGET = 0x82B80C0;
const R = 0x9839FF8;
const out = { target: TARGET, host: null, entries: {}, events: [], errors: [], pad: '0x0',
              dispatched: 0, skipped: 0 };
let padMask = '0x0';

Interceptor.attach(base.add(RVA.hid_update), {
  onEnter() { hle.add(HLE.pad_buttons).writeU64(uint64(padMask)); }
});

const host = resolveGuest(TARGET);
out.host = host ? host.toString() : null;
if (host) {
  Interceptor.attach(host, {
    onEnter(args) {
      let entry = null;
      try { entry = parseInt(args[1].toString(), 16); } catch (e) { entry = -1; }
      out.entries[entry.toString(16)] = (out.entries[entry.toString(16)] || 0) + 1;
      if (entry !== TARGET) { out.skipped++; return; }
      out.dispatched++;
      if (out.events.length >= 4000) return;
      try {
        const cpu = args[0];
        const x0 = parseInt(cpu.add(0).readPointer().toString(), 16);
        const lr = parseInt(cpu.add(30 * 8).readPointer().toString(), 16);
        if (!x0) { out.errors.push('null event'); return; }
        const type = gm.add(ptr(x0)).readU32();
        const player = gm.add(ptr(x0 + 0x28)).readU32();
        const bit = gm.add(ptr(x0 + 0x2C)).readU32();
        const rec = {
          t: Date.now(), type, player, bit, lr: '0x' + lr.toString(16),
          tid: Process.getCurrentThreadId(),
          raw: hexBytes(x0, 0x48)
        };
        if (player < 4) {
          const base = R + player * 0x10C;
          rec.old = gm.add(ptr(base + 0x338)).readU32();
          rec.now = gm.add(ptr(base + 0x370)).readU32();
        }
        out.events.push(rec);
      } catch (e) { if (out.errors.length < 10) out.errors.push(e.message); }
    }
  });
}
rpc.exports = {
  setPad(v) { padMask = '0x' + v.toString(16); out.pad = padMask; },
  data: () => out,
  stop() { padMask = '0x0'; hle.add(HLE.pad_buttons).writeU64(uint64('0x0')); return out; }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync
    # Diagnostic positives through the runtime's own sampler: A (bit 0) and
    # Plus (bit 12).  ZL/ZR (bits 6/7) are skipped by this event loop.
    plan = [("idle", 0x0, 0.5), ("A", 0x1, 0.5), ("A_up", 0x0, 0.4),
            ("Plus", 0x400, 0.5), ("Plus_up", 0x0, 0.4)]
    try:
        for name, mask, seconds in plan:
            api.set_pad(mask)
            time.sleep(seconds)
    finally:
        data = api.stop()
        session.detach()

    events = data.get("events", [])
    summary = {}
    for ev in events:
        key = (ev.get("type"), ev.get("player"), ev.get("bit"))
        summary[key] = summary.get(key, 0) + 1
    print("target", hex(data["target"]), "host", data["host"],
          "dispatched", data.get("dispatched"), "skipped", data.get("skipped"))
    print("entries", data.get("entries"))
    print("errors", data.get("errors")[:4])
    print("types {type, player, bit}: count")
    for key in sorted(summary, key=lambda k: (k[0] is None, k)):
        print("  ", key, summary[key])
    text = json.dumps({"pid": args.pid, **data}, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
