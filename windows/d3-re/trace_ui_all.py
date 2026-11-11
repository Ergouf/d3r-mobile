#!/usr/bin/env python3
"""Hook every D3 console UI callback through the runtime's host dispatch table.

The console UI table at guest main+0x1876f20 holds {name, hash, handler} entries.
`handler` is a guest address; the runtime executes it through the host function
published in `g_disp[(handler - g_code_lo) >> 2]`. Hooking the guest view address
fails (it is a data copy), so this probe resolves every handler to its real host
function before attaching.

Press keys in the game while it runs; every handler hit is printed once with its
first arguments and a backtrace mapped back to guest entry points.

Usage:
  python windows/d3-re/trace_ui_all.py --pid 22876 --seconds 25
"""
from __future__ import annotations

import argparse
import json
import time

import frida

# globals in the current scarletnx.exe (llvm-nm | findstr " g_disp$ g_code_lo$")
G_DISP_OFFSET = 0x12910E0
G_CODE_LO_OFFSET = 0x17AF028
TABLE_OFFSET = 0x1876F20
ENTRY_SIZE = 0x18

JS = r"""
const G_DISP = PAYLOAD.g_disp;
const G_CODE_LO = PAYLOAD.code_lo;
const TABLE_OFFSET = PAYLOAD.table_offset;
const ENTRY_SIZE = 0x18;
try {
  const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
  if (!exe) throw new Error('runtime exe not found');
  const disp = exe.base.add(G_DISP).readPointer();
  const codeLo = exe.base.add(G_CODE_LO).readU64();

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
  if (!main) throw new Error('main module missing');

  let host = null;
  for (const r of Process.enumerateRanges('rw-')) if (r.size === main.size.toNumber()) { host = r.base; break; }
  if (!host) throw new Error('main view missing');

  const table = host.add(TABLE_OFFSET);
  const entries = [];
  for (let i = 0; i < 1000; i++) {
    const e = table.add(i * ENTRY_SIZE);
    const namep = e.readPointer();
    if (namep.compare(main.base) < 0 || namep.compare(main.base.add(main.size)) >= 0) break;
    const handler = e.add(0x10).readPointer();
    let name = null;
    try {
      const off = namep.sub(main.base).toUInt32();
      const bytes = new Uint8Array(host.add(off).readByteArray(160));
      let s = '';
      for (let k = 0; k < bytes.length && bytes[k] !== 0; k++) s += String.fromCharCode(bytes[k]);
      name = s;
    } catch (err) {}
    if (handler.isNull() || handler.compare(main.base) < 0 || handler.compare(main.base.add(main.size)) >= 0) continue;
    entries.push({i, name, handler});
  }

  // map host code addresses back to guest entries for backtraces
  const nentries = p.add(16).readU32(), ea = p.add(24).readPointer(), ef = p.add(32).readPointer();
  const all = [];
  for (let i = 0; i < nentries; i++) all.push([ef.add(i * 8).readPointer(), ea.add(i * 8).readPointer()]);
  all.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  function near(a) {
    let lo = 0, hi = all.length - 1, best = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (all[mid][0].compare(a) <= 0) { best = mid; lo = mid + 1; } else hi = mid - 1; }
    if (best < 0) return null;
    return all[best][1].toString() + '+' + a.sub(all[best][0]).toString();
  }

  const hosts = new Map();
  for (const e of entries) {
    const off = e.handler.sub(codeLo).toUInt32();
    if (off & 3) continue;
    const fn = disp.add((off >>> 2) * 8).readPointer();
    if (fn.isNull()) continue;
    const key = fn.toString();
    if (!hosts.has(key)) hosts.set(key, {fn, names: [], guests: []});
    const h = hosts.get(key);
    h.names.push(e.name);
    h.guests.push(e.handler.toString());
  }

  let hooked = 0, failed = 0;
  for (const [key, h] of hosts) {
    try {
      const state = {count: 0};
      Interceptor.attach(h.fn, {
        onEnter(args) {
          state.count++;
          if (state.count > 3) return;
          const ctx = this.context;
          let x0mem = null;
          try {
            if (!ctx.x0.isNull()) x0mem = ctx.x0.readPointer().toString();
          } catch (err) { x0mem = 'ERR ' + err.message; }
          send({event: 'hit', host: key, names: h.names, guests: h.guests, count: state.count,
                x0: ctx.x0.toString(), x1: ctx.x1.toString(), x2: ctx.x2.toString(), x3: ctx.x3.toString(),
                x0mem, lr: ctx.lr.toString(), near_lr: near(ctx.lr),
                bt: Thread.backtrace(ctx, Backtracer.ACCURATE).slice(0, 8).map(a => near(a))});
        }
      });
      hooked++;
    } catch (e) {
      failed++;
      send({event: 'hookfail', host: key, names: h.names, error: e.message});
    }
  }
  send({event: 'ready', entries: entries.length, unique: hosts.size, hooked, failed});
} catch (e) { send({event: 'error', error: e.message, stack: e.stack}); }
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=20.0)
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.pid)
    payload = {"g_disp": G_DISP_OFFSET, "code_lo": G_CODE_LO_OFFSET, "table_offset": TABLE_OFFSET}
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))
    started = time.time()

    def on_message(message, data):
        p = message.get("payload", {})
        if p.get("event") == "hit":
            print("HIT", p["names"][:2], p["guests"][:1], f"x0={p['x0']} x1={p['x1']} x2={p['x2']} x3={p['x3']}")
            print("    lr", p.get("lr"), p.get("near_lr"), "bt", p.get("bt"))
        elif p.get("event") in ("ready", "error", "hookfail"):
            print(p)

    script.on("message", on_message)
    script.load()
    time.sleep(max(0.0, args.seconds - (time.time() - started)))
    session.detach()


if __name__ == "__main__":
    main()
