#!/usr/bin/env python3
"""Call a guest function from the running ScarletNX process (read-only probe).

This is the B2 feasibility probe: it copies a live guest CPU state, points it at
a guest function, and runs that function through the recompiler dispatch table.
The first target is the pure djb2 hash function `FUN_00a49790`, which proves the
call path without touching game state.

Usage:
  python windows/d3-re/call_guest.py --pid 28308 --guest 0x8a49790 --arg 0x8dcf212
  python windows/d3-re/call_guest.py --guest 0x8a49790 --arg 0x8dcf212   # spawn a throwaway
"""
from __future__ import annotations

import argparse
import json
import time

import frida

DEFAULT_EXE = r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
DEFAULT_CWD = r"D:\Games\DiabloIII\01001B300B9BE000"

JS = r"""
const TARGET = ptr(PAYLOAD.target);
const ARGS = PAYLOAD.args.map(x => ptr(x));
const MAX_STEPS = PAYLOAD.maxSteps;
setImmediate(() => {
try {
  const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
  if (!mod) throw new Error('game code module not loaded');
  const exp = mod.findExportByName('snx_module');
  const p = new NativeFunction(exp, 'pointer', [])();
  const mods = p.add(8).readPointer();
  let main = null;
  for (let i = 0; i < p.add(4).readU32(); i++) {
    const m = mods.add(i * 88);
    if (m.readPointer().readCString() === 'main') main = {base: m.add(8).readPointer(), size: m.add(16).readU64()};
  }
  if (!main) throw new Error('main module not found');
  const nentries = p.add(16).readU32();
  const entryAddr = p.add(24).readPointer();
  const entryFn = p.add(32).readPointer();
  const codeLo = p.add(48).readPointer();
  const codeHi = p.add(56).readPointer();
  const interp = p.add(40).readPointer();

  let host = null;
  for (const r of Process.enumerateRanges('rw-')) {
    if (r.size === main.size.toNumber()) { host = r.base; break; }
  }
  if (!host) throw new Error('main host view not found');
  const gmem = host.sub(main.base);

  function ptrBytes(ptrVal) {
    const tmp = Memory.alloc(8);
    tmp.writePointer(ptrVal);
    return Array.from(new Uint8Array(tmp.readByteArray(8))).map(x => x.toString(16).padStart(2, '0')).join('');
  }
  const hex = ptrBytes(gmem);

  // Find one live CPU struct: its mem field points at the main view's guest 0.
  let cpu = null;
  const ranges = Process.enumerateRanges('rw-').filter(r => r.size <= 8 * 1024 * 1024).sort((a, b) => a.size - b.size);
  send({event: 'stage', stage: 'scan', ranges: ranges.length});
  let scanned = 0;
  for (const r of ranges) {
    let ms = [];
    try { ms = Memory.scanSync(r.base, r.size, hex); } catch (e) { continue; }
    scanned++;
    for (const m of ms) {
      const cand = m.address.sub(848);
      try {
        const disp = cand.add(856).readPointer();
        const lo = cand.add(864).readPointer();
        const hi = cand.add(872).readPointer();
        if (lo.compare(codeLo) === 0 && hi.compare(codeHi) === 0 && Process.findRangeByAddress(disp)) {
          cpu = cand; break;
        }
      } catch (e) {}
    }
    if (cpu) break;
  }
  send({event: 'stage', stage: 'scan-done', scanned});
  if (!cpu) throw new Error('live CPU not found');

  const copy = Memory.alloc(1024);
  Memory.copy(copy, cpu, 1024);
  for (let i = 0; i < 8; i++) copy.add(i * 8).writePointer(i < ARGS.length ? ARGS[i] : ptr(0));
  copy.add(8 * 30).writePointer(ptr(0));                 // x30 = 0: returning ends the run
  const liveSp = copy.add(8 * 31).readPointer();
  copy.add(8 * 31).writePointer(liveSp.sub(0x8000));      // scratch room below the live stack
  copy.add(256).writePointer(TARGET);                     // pc
  copy.add(264).writeU32(0);

  const disp = copy.add(856).readPointer();
  const lo = copy.add(864).readPointer();
  const hi = copy.add(872).readPointer();
  const events = [];
  let steps = 0, lastPc = null;
  while (steps < MAX_STEPS) {
    const pc = copy.add(256).readPointer();
    if (pc.isNull()) break;
    if (pc.compare(lo) < 0 || pc.compare(hi) >= 0) { events.push('pc out of range: ' + pc); break; }
    const off = pc.sub(lo).toUInt32();
    if (off & 3) { events.push('unaligned pc: ' + pc); break; }
    const fn = disp.add((off >>> 2) * 8).readPointer();
    if (fn.isNull()) { events.push('no function for pc: ' + pc); break; }
    lastPc = pc.toString();
    const f = new NativeFunction(fn, 'void', ['pointer', 'uint64']);
    f(copy, pc);
    steps++;
  }
  const ret = copy.add(0).readPointer();
  send({ok: true, steps, ret: ret.toString(), retNum: ret.toUInt32 ? ret.toUInt32() : null,
        lastPc, cpu: cpu.toString(), guestBase: main.base.toString(), host: host.toString()});
} catch (e) { send({ok: false, error: e.message, stack: e.stack}); }
});
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--guest", required=True, help="guest function address (absolute, e.g. 0x8a49790)")
    ap.add_argument("--arg", action="append", default=[], help="guest argument (hex), up to 8")
    ap.add_argument("--max-steps", type=int, default=200000)
    ap.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the probe result")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--spawn-wait", type=float, default=50.0)
    ap.add_argument("--exe", default=DEFAULT_EXE)
    ap.add_argument("--cwd", default=DEFAULT_CWD)
    args = ap.parse_args()

    payload = {
        "target": hex(int(args.guest, 16)),
        "args": [hex(int(a, 16)) for a in args.arg],
        "maxSteps": args.max_steps,
    }
    device = frida.get_local_device()
    pid = args.pid
    spawned = False
    if pid is None:
        pid = device.spawn([args.exe], cwd=args.cwd)
        spawned = True
        device.resume(pid)
        time.sleep(args.spawn_wait)
    session = device.attach(pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))
    result: list[dict] = []

    def on_message(m, d):
        p = m.get("payload", {})
        if p.get("event") == "stage":
            print("stage:", p, flush=True)
        else:
            result.append(p)

    script.on("message", on_message)
    script.load()
    deadline = time.time() + args.wait
    while time.time() < deadline and not result:
        time.sleep(0.5)
    session.detach()
    print(json.dumps(result[0] if result else {"ok": False, "error": "no message"}, indent=2))
    if spawned:
        device.kill(pid)


if __name__ == "__main__":
    main()
