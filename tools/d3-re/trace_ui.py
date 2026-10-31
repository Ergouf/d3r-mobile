#!/usr/bin/env python3
"""Trace D3 guest UI handlers while sending a key to the game window.

The runtime recompiles guest code into 01001B300B9BE000_code.dll. `snx_module`
lists every guest entry address and its host function, so a guest function can be
hooked without guessing a host address. The backtrace is mapped back to guest
offsets by the same table (nearest entry), which is enough to identify callers.

Usage:
  python tools/d3-re/trace_ui.py --guest 0x8366870 --key space --seconds 8
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
  const nentries = p.add(16).readU32();
  const entryAddr = p.add(24).readPointer();
  const entryFn = p.add(32).readPointer();

  // Build a host -> guest map for the requested entries and a sorted array for
  // nearest-entry backtrace mapping.
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
  function frameInfo(ctx) {
    return Thread.backtrace(ctx, Backtracer.ACCURATE).map(a => ({
      host: a.toString(),
      sym: (() => { try { return DebugSymbol.fromAddress(a).toString(); } catch (e) { return null; } })(),
      near: nearest(a),
      module: (() => { try { const m = Process.findModuleByAddress(a); return m ? m.name + '+' + a.sub(m.base).toString(16) : null; } catch (e) { return null; } })()
    }));
  }

  const out = {main: main ? main.base.toString() : null, nentries, hooks: []};
  for (const [g, h] of wanted) {
    try {
      Interceptor.attach(h, {
        onEnter(args) {
          const ctx = this.context;
          let gx = [];
          try {
            const cpu = args[0];
            for (let i = 0; i < 8; i++) gx.push(cpu.add(i * 8).readPointer().toString());
          } catch (e) { gx = ['ERR ' + e.message]; }
          send({event: 'enter', guest: g, host: h.toString(),
                x0: ctx.x0.toString(), x1: ctx.x1.toString(), x2: ctx.x2.toString(), x3: ctx.x3.toString(),
                x4: ctx.x4.toString(), x5: ctx.x5.toString(), gx,
                bt: frameInfo(ctx)});
        },
        onLeave(retval) { send({event: 'leave', guest: g, ret: retval.toString()}); }
      });
      out.hooks.push({guest: g, host: h.toString()});
    } catch (e) {
      out.hooks.push({guest: g, error: e.message});
    }
  }
  send(out);
}
"""


def find_window(pid: int) -> int | None:
    user32 = ctypes.windll.user32
    found: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _):
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return found[0] if found else None


def send_key(hwnd: int, vk: int, hold: float = 0.12) -> None:
    user32 = ctypes.windll.user32
    # Post to the window so the game receives it even when another window has
    # the foreground; SDL translates WM_KEYDOWN in its WndProc.
    user32.PostMessageW(hwnd, 0x0100, vk, 0x00390001)
    time.sleep(hold)
    user32.PostMessageW(hwnd, 0x0101, vk, 0xC0390001)


KEYS = {"space": 0x20, "enter": 0x0D, "escape": 0x1B, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest", action="append", required=True, help="guest function address, e.g. 0x8366870")
    parser.add_argument("--key", choices=sorted(KEYS), default="space")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--exe", default=DEFAULT_EXE)
    parser.add_argument("--cwd", default=DEFAULT_CWD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    guests = [hex(int(g, 16)) for g in args.guest]
    device = frida.get_local_device()
    pid = args.pid
    spawned = False
    if pid is None:
        pid = device.spawn([args.exe], cwd=args.cwd)
        spawned = True
        device.resume(pid)
        time.sleep(9)

    session = device.attach(pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(guests)))
    messages: list[dict] = []

    def on_message(message, data):
        payload = message.get("payload", {})
        messages.append(payload)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        elif payload.get("event") == "enter":
            print(f"ENTER {payload['guest']} x0={payload['x0']} x1={payload['x1']} x2={payload['x2']} x3={payload['x3']} gx={payload.get('gx')}")
            for frame in payload.get("bt", [])[:10]:
                print("  ", frame.get("module"), frame.get("near"), frame.get("sym"))
        elif payload.get("hooks"):
            print("HOOKS", json.dumps(payload.get("hooks"), ensure_ascii=False))
        elif payload.get("error"):
            print("ERROR", payload)

    script.on("message", on_message)
    script.load()
    time.sleep(1.0)

    hwnd = find_window(pid)
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    print(f"sending {args.key} to hwnd={hwnd}")
    if hwnd:
        send_key(hwnd, KEYS[args.key])
    time.sleep(args.seconds)

    session.detach()
    if spawned:
        device.kill(pid)


if __name__ == "__main__":
    main()
