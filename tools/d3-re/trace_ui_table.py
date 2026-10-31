#!/usr/bin/env python3
"""Hook every D3 console UI callback and log which one a scripted press reaches.

The table at guest main+0x1876f20 holds {name, hash, handler} entries. The
runtime's unattended `--script=` option presses controller buttons on a timer
(1 = A, 2 = B, 0x1000 = left, ...), so no window focus or synthetic keyboard
input is needed.

Usage:
  python tools/d3-re/trace_ui_table.py --script 12000:1,15000:1 --seconds 12
"""
from __future__ import annotations

import argparse
import json
import time

import frida

DEFAULT_EXE = r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
DEFAULT_CWD = r"D:\Games\DiabloIII\01001B300B9BE000"
TABLE_OFFSET = 0x1876F20
ENTRY_SIZE = 0x18

JS = r"""
try {
  const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
  if (!mod) { send({error: 'game code module not loaded'}); }
  else {
    const exp = mod.findExportByName('snx_module');
    const p = new NativeFunction(exp, 'pointer', [])();
    const mods = p.add(8).readPointer();
    let main = null;
    for (let i = 0; i < p.add(4).readU32(); i++) {
      const m = mods.add(i * 88);
      if (m.readPointer().readCString() === 'main') main = {base: m.add(8).readPointer(), size: m.add(16).readU64()};
    }
    if (!main) { send({error: 'main module missing'}); }
    else {
      let host = null;
      for (const r of Process.enumerateRanges('rw-')) if (r.size === main.size.toNumber()) { host = r.base; break; }
      if (!host) { send({error: 'main view missing'}); }
      else {
        const table = host.add(0x1876f20);
        const entries = [];
        for (let i = 0; i < 1000; i++) {
          const e = table.add(i * 0x18);
          const namep = e.readPointer();
          if (namep.compare(main.base) < 0 || namep.compare(main.base.add(main.size)) >= 0) break;
          const hash = e.add(8).readU32();
          const handler = e.add(0x10).readPointer();
          let name = null;
          try {
            const off = namep.sub(main.base).toUInt32();
            const bytes = new Uint8Array(host.add(off).readByteArray(160));
            let s = '';
            for (let k = 0; k < bytes.length && bytes[k] !== 0; k++) s += String.fromCharCode(bytes[k]);
            name = s;
          } catch (err) {}
          entries.push({i, name, hash, handler: handler.toString(), handlerOffset: handler.sub(main.base).toUInt32()});
        }
        const byHandler = new Map();
        for (const e of entries) {
          if (e.handler === '0x0') continue;
          if (!byHandler.has(e.handler)) byHandler.set(e.handler, []);
          byHandler.get(e.handler).push(e.name);
        }
        const hooks = [];
        for (const [handler, names] of byHandler) {
          try {
            Interceptor.attach(ptr(handler), {
              onEnter(args) {
                const c = this.context;
                send({event: 'ui', handler, names, x0: c.x0.toString(), x1: c.x1.toString(),
                      x2: c.x2.toString(), x3: c.x3.toString(),
                      bt: Thread.backtrace(c, Backtracer.ACCURATE).slice(0, 8).map(a => a.toString())});
              }
            });
            hooks.push({handler, names});
          } catch (e) {
            hooks.push({handler, names, error: e.message});
          }
        }
        send({table: entries.length, hooks});
      }
    }
  }
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True, help="unattended press script, e.g. 12000:1,15000:1")
    parser.add_argument("--press-len", type=int, default=120)
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--spawn-wait", type=float, default=9.0)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--exe", default=DEFAULT_EXE)
    parser.add_argument("--cwd", default=DEFAULT_CWD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    device = frida.get_local_device()
    pid = args.pid
    spawned = False
    if pid is None:
        argv = [args.exe, f"--script={args.script}", f"--press_len={args.press_len}"]
        pid = device.spawn(argv, cwd=args.cwd)
        spawned = True
        device.resume(pid)
        time.sleep(args.spawn_wait)

    session = device.attach(pid)
    script = session.create_script(JS)
    started = time.time()

    def on_message(message, data):
        payload = message.get("payload", {})
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return
        if payload.get("event") == "ui":
            names = payload.get("names", [])
            print(f"UI {payload['handler']} {names} x0={payload['x0']} x1={payload['x1']} x2={payload['x2']} x3={payload['x3']}")
            for a in payload.get("bt", [])[:6]:
                print("   ", a)
        elif payload.get("hooks") is not None:
            print(f"TABLE {payload.get('table')} unique handlers {len(payload['hooks'])}")
        elif payload.get("error"):
            print("ERROR", payload)

    script.on("message", on_message)
    script.load()
    time.sleep(max(0.0, args.seconds - (time.time() - started)))
    session.detach()
    if spawned:
        device.kill(pid)


if __name__ == "__main__":
    main()
