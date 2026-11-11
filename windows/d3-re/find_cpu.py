#!/usr/bin/env python3
"""Find a guest CPU struct in the running ScarletNX process.

The runtime keeps each guest thread's registers and the JIT dispatch table in a
`CPU` struct. `CPU.mem` (offset 848) is the host base of guest address 0, and
`CPU.disp` (offset 856) maps guest code words to the host functions the thread
actually calls. Finding a CPU lets a probe hook the JIT-compiled function rather
than the possibly unused AOT entry.

Usage:
  python windows/d3-re/find_cpu.py --guest 0x8366870 --guest 0x8017ca8
"""
from __future__ import annotations

import argparse
import json
import time

import frida

DEFAULT_EXE = r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
DEFAULT_CWD = r"D:\Games\DiabloIII\01001B300B9BE000"

JS = r"""
const GUESTS = PAYLOAD;
try {
  const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
  const exp = mod.findExportByName('snx_module');
  const p = new NativeFunction(exp, 'pointer', [])();
  const mods = p.add(8).readPointer();
  let main = null;
  for (let i = 0; i < p.add(4).readU32(); i++) {
    const m = mods.add(i * 88);
    if (m.readPointer().readCString() === 'main') main = {base: m.add(8).readPointer(), size: m.add(16).readU64()};
  }
  let host = null;
  for (const r of Process.enumerateRanges('rw-')) {
    if (r.size === main.size.toNumber()) { host = r.base; break; }
  }
  const gmem = host.sub(main.base);
  const codeLo = p.add(48).readPointer();
  const codeHi = p.add(56).readPointer();
  const pat = [];
  const b = gmem.toMatchPattern ? null : null;
  // build a byte pattern from the pointer
  const bytes = new Uint8Array(gmem.toByteArray ? gmem.toByteArray() : []);
  // Frida pointers have no toByteArray; use Memory read from a local buffer instead.
  function ptrBytes(ptrVal) {
    const tmp = Memory.alloc(8);
    tmp.writePointer(ptrVal);
    return Array.from(new Uint8Array(tmp.readByteArray(8))).map(x => x.toString(16).padStart(2, '0')).join('');
  }
  const hex = ptrBytes(gmem);
  const hits = [];
  for (const r of Process.enumerateRanges('rw-')) {
    if (r.size > 64 * 1024 * 1024) continue;
    let ms = [];
    try { ms = Memory.scanSync(r.base, r.size, hex); } catch (e) { continue; }
    for (const m of ms) {
      const cpu = m.address.sub(848);
      let ok = false, disp = null, lo = null, hi = null, pc = null;
      try {
        disp = cpu.add(856).readPointer();
        lo = cpu.add(864).readPointer();
        hi = cpu.add(872).readPointer();
        pc = cpu.add(256).readPointer();
        const dr = Process.findRangeByAddress(disp);
        ok = dr !== null && lo.compare(codeLo) === 0 && hi.compare(codeHi) === 0;
      } catch (e) {}
      if (!ok) continue;
      const entries = {};
      for (const g of GUESTS) {
        try {
          const ga = ptr(g);
          const off = ga.sub(codeLo).toUInt32();
          const fn = disp.add((off >>> 2) * 8).readPointer();
          entries[g] = fn.toString();
        } catch (e) { entries[g] = 'ERR ' + e.message; }
      }
      hits.push({cpu: cpu.toString(), range: r.base.toString(), disp: disp.toString(), lo: lo.toString(),
                 hi: hi.toString(), pc: pc.toString(),
                 x0: cpu.readPointer().toString(), x1: cpu.add(8).readPointer().toString(),
                 entries});
    }
  }
  send({base: main.base.toString(), host: host.toString(), gmem: gmem.toString(),
        codeLo: codeLo.toString(), codeHi: codeHi.toString(), hits});
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest", action="append", default=[], help="guest address to resolve through CPU.disp")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--spawn-wait", type=float, default=50.0)
    parser.add_argument("--exe", default=DEFAULT_EXE)
    parser.add_argument("--cwd", default=DEFAULT_CWD)
    parser.add_argument("--script", default="5000:1,15000:1,25000:1,35000:1,48000:400")
    args = parser.parse_args()

    guests = [hex(int(g, 16)) for g in args.guest]
    device = frida.get_local_device()
    pid = args.pid
    spawned = False
    if pid is None:
        pid = device.spawn([args.exe, f"--script={args.script}", "--press_len=250"], cwd=args.cwd)
        spawned = True
        device.resume(pid)
        time.sleep(args.spawn_wait)
    session = device.attach(pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(guests)))
    result: list[dict] = []
    script.on("message", lambda m, d: result.append(m.get("payload", {})))
    script.load()
    time.sleep(5)
    session.detach()
    out = result[0] if result else {"error": "no message"}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if spawned:
        device.kill(pid)


if __name__ == "__main__":
    main()
