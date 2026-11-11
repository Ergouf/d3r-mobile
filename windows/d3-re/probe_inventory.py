#!/usr/bin/env python3
"""Watch D3 UI handlers while the game loads and a key is posted.

The game's console UI handlers are often continuation blocks inside a state
machine, so a handler entry may be called without its function prologue. This
probe records the guest arguments and the nearest AOT entry for every backtrace
frame, which identifies the state machine's caller.

Usage:
  python windows/d3-re/probe_inventory.py --seconds 55
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
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
  const nentries = p.add(16).readU32();
  const entryAddr = p.add(24).readPointer();
  const entryFn = p.add(32).readPointer();
  const wanted = new Map();
  const all = [];
  for (let i = 0; i < nentries; i++) {
    const ga = entryAddr.add(i * 8).readPointer();
    const ha = entryFn.add(i * 8).readPointer();
    all.push([ha, ga]);
    const key = ga.toString();
    if (GUESTS.includes(key) && !wanted.has(key)) wanted.set(key, ha);
  }
  all.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  function nearest(addr) {
    let lo = 0, hi = all.length - 1, best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (all[mid][0].compare(addr) <= 0) { best = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    if (best < 0) return null;
    const [h, g] = all[best];
    return {guest: g.toString(), delta: addr.sub(h).toString()};
  }
  function frames(ctx) {
    return Thread.backtrace(ctx, Backtracer.ACCURATE).slice(0, 12).map(a => {
      let mod = null;
      try { const m = Process.findModuleByAddress(a); mod = m ? m.name + '+' + a.sub(m.base).toString(16) : null; } catch (e) {}
      return {host: a.toString(), near: nearest(a), module: mod};
    });
  }
  const counts = {};
  for (const [g, h] of wanted) {
    counts[g] = 0;
    try {
      Interceptor.attach(h, {
        onEnter(args) {
          counts[g]++;
          if (counts[g] > 12) return;
          let gx = [];
          let pc = null;
          try {
            const cpu = args[0];
            for (let i = 0; i < 8; i++) gx.push(cpu.add(i * 8).readPointer().toString());
            pc = cpu.add(256).readPointer().toString();
          } catch (e) { gx = ['ERR ' + e.message]; }
          send({event: 'enter', guest: g, gx, pc, bt: frames(this.context)});
        }
      });
    } catch (e) {
      send({event: 'hook-error', guest: g, error: e.message});
    }
  }
  send({event: 'hooks', guests: [...wanted.keys()]});
} catch (e) { send({event: 'error', error: e.message, stack: e.stack}); }
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest", action="append", default=[
        "0x836c110",  # UIInventory_YieldFocus
        "0x81fb910",  # UIInventory_OnButton1
        "0x81fb920",  # UIInventory_OnButton2
        "0x83c7900",  # Console_Pause
    ])
    parser.add_argument("--script", default="5000:1,15000:1,25000:1,35000:1,45000:400")
    parser.add_argument("--press-len", type=int, default=500)
    parser.add_argument("--spawn-wait", type=float, default=8.0)
    parser.add_argument("--seconds", type=float, default=55.0)
    parser.add_argument("--post-at", type=float, default=46.0, help="seconds after spawn to start posting Space")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    device = frida.get_local_device()
    pid = args.pid
    proc = None
    if pid is None:
        import subprocess
        proc = subprocess.Popen(
            [DEFAULT_EXE, f"--script={args.script}", f"--press_len={args.press_len}"],
            cwd=DEFAULT_CWD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = proc.pid
        time.sleep(args.spawn_wait)

    session = device.attach(pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps([hex(int(g, 16)) for g in args.guest])))

    def on_message(message, data):
        payload = message.get("payload", {})
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return
        if payload.get("event") == "enter":
            print(f"ENTER {payload['guest']} gx={payload['gx']} pc={payload['pc']}")
            for f in payload.get("bt", [])[:8]:
                print("   ", f.get("module"), f.get("near"))
        else:
            print(payload)

    script.on("message", on_message)
    script.load()
    time.sleep(0.5)

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def enum_cb(hwnd, _):
        wp = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
        if wp.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(enum_cb, 0)
    hwnd = found[0] if found else None
    print(f"pid={pid} hwnd={hex(hwnd) if hwnd else None}")

    started = time.time()
    last_post = 0.0
    while time.time() - started < args.seconds:
        elapsed = time.time() - started + args.spawn_wait
        if hwnd and elapsed >= args.post_at and time.time() - last_post >= 3.0:
            last_post = time.time()
            user32.PostMessageW(hwnd, 0x0100, 0x20, 0x00390001)
            time.sleep(0.12)
            user32.PostMessageW(hwnd, 0x0101, 0x20, 0xC0390001)
        time.sleep(0.1)

    session.detach()
    if proc:
        proc.kill()


if __name__ == "__main__":
    main()
