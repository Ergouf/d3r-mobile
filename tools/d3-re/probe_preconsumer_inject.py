"""Pre-consumer logical-bit injection with the event observer.

Injection point: the game calls 0x800F9F0 right before the per-player bit loop
(return address 0x82B94E0), after the input manager has written the current
logical word to R + p*0x10C + 0x370 and before 0x82B9500 reads it.  The hook
filters on the GuestFn entry (args[1]) and on that exact LR, then ORs the
requested logical bit into the current word for the requested player.  This
runs on the game thread in its own frame phase, not on a timer.

The dispatch observer at 0x82B80C0 records the resulting event sequence.

Usage:
  python tools/d3-re/probe_preconsumer_inject.py --pid <pid> [--out ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida

import version

JS = version.js_consts() + r"""
const TARGET_EVENT = 0x82B80C0;
const TICK = 0x800F9F0;
const PRE_LR = 0x82B94E0;       /* return address of the call right before the bit loop */
const R = 0x9839FF8;
const out = { hosts: {}, events: [], write_log: [], errors: [], tick_hits: 0, tick_matched: 0,
              ent_event: {}, ent_tick: {} };
let injBit = 0, injPlayer = 0;

function hook(guest, onEnter) {
  const h = resolveGuest(guest);
  out.hosts[guest.toString(16)] = h ? h.toString() : null;
  if (h) Interceptor.attach(h, { onEnter });
  return !!h;
}

hook(TICK, (args) => {
  let entry = -1;
  try { entry = parseInt(args[1].toString(), 16); } catch (e) { return; }
  out.ent_tick[entry.toString(16)] = (out.ent_tick[entry.toString(16)] || 0) + 1;
  if (entry !== TICK) return;
  out.tick_hits++;
  if (!injBit) return;
  try {
    const cpu = args[0];
    const lr = parseInt(cpu.add(30 * 8).readPointer().toString(), 16);
    if (lr !== PRE_LR) return;
    const player = parseInt(cpu.add(19 * 8).readPointer().toString(), 16);
    const r = parseInt(cpu.add(24 * 8).readPointer().toString(), 16);
    if (player !== injPlayer || r !== R) return;
    const p = R + player * 0x10C + 0x370;
    const old = gm.add(ptr(p)).readU32();
    gm.add(ptr(p)).writeU32((old | injBit) >>> 0);
    out.tick_matched++;
    if (out.write_log.length < 200) {
      out.write_log.push({ t: Date.now(), player, before: old, after: (old | injBit) >>> 0,
                           lr: '0x' + lr.toString(16) });
    }
  } catch (e) { if (out.errors.length < 10) out.errors.push('t:' + e.message); }
});

hook(TARGET_EVENT, (args) => {
  let entry = -1;
  try { entry = parseInt(args[1].toString(), 16); } catch (e) { return; }
  out.ent_event[entry.toString(16)] = (out.ent_event[entry.toString(16)] || 0) + 1;
  if (entry !== TARGET_EVENT) return;
  if (out.events.length >= 4000) return;
  try {
    const cpu = args[0];
    const x0 = parseInt(cpu.add(0).readPointer().toString(), 16);
    const lr = parseInt(cpu.add(30 * 8).readPointer().toString(), 16);
    if (!x0) { out.errors.push('null event'); return; }
    const type = gm.add(ptr(x0)).readU32();
    const player = gm.add(ptr(x0 + 0x28)).readU32();
    const bit = gm.add(ptr(x0 + 0x2C)).readU32();
    const rec = { t: Date.now(), type, player, bit, lr: '0x' + lr.toString(16),
                  tid: Process.getCurrentThreadId(), raw: hexBytes(x0, 0x48) };
    if (player < 4) {
      const b = R + player * 0x10C;
      rec.old = gm.add(ptr(b + 0x338)).readU32();
      rec.now = gm.add(ptr(b + 0x370)).readU32();
    }
    out.events.push(rec);
  } catch (e) { if (out.errors.length < 10) out.errors.push('e:' + e.message); }
});

rpc.exports = {
  setInject(bit, player) { injBit = bit; injPlayer = player || 0; },
  data: () => out
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
    plan = [("idle0", 0, 0.6), ("plus", 0x1000, 1.0), ("plus_up", 0, 0.8),
            ("a", 0x1, 1.0), ("a_up", 0, 0.8)]
    marks = []
    try:
        for name, bit, seconds in plan:
            api.set_inject(bit, 0)
            marks.append({"name": name, "bit": hex(bit), "t": int(time.time() * 1000)})
            time.sleep(seconds)
    finally:
        api.set_inject(0, 0)
        data = api.data()
        session.detach()

    events = data.get("events", [])
    summary = {}
    for ev in events:
        key = (ev.get("type"), ev.get("player"), ev.get("bit"))
        summary[key] = summary.get(key, 0) + 1
    print("hosts", data.get("hosts"))
    print("tick hits", data.get("tick_hits"), "matched", data.get("tick_matched"),
          "event entries", data.get("ent_event"), "tick entries", data.get("ent_tick"))
    print("errors", data.get("errors")[:4])
    for key in sorted(summary, key=lambda k: (k[0] is None, k)):
        if key[0] in (29, 30, 33):
            print("  ", key, summary[key])
    print("writes", len(data.get("write_log", [])))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"pid": args.pid, "marks": marks, **data}, indent=2)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
