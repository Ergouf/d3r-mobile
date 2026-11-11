#!/usr/bin/env python3
"""Trace a guest UI handler through the runtime's JIT dispatch slot (CPU.disp).

The AOT entry table is not what the UI calls: the JIT publishes its own host
function in `g_disp[(pc - g_code_lo) >> 2]`. This probe reads those two globals
from the runtime executable, hooks the actual host function, presses a key, and
prints the registers and the backtrace mapped back to guest addresses.

Usage:
  python windows/d3-re/trace_ui_disp.py --pid 20152 --guest 0x8366870 --key space
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import time

import frida

# globals in the current scarletnx.exe (llvm-nm | findstr " g_disp$ g_code_lo$")
G_DISP_OFFSET = 0x12910E0
G_CODE_LO_OFFSET = 0x17AF028

JS = r"""
const TARGET = ptr(PAYLOAD.target);
const G_DISP = PAYLOAD.g_disp;
const G_CODE_LO = PAYLOAD.code_lo;
try {
  const exe = Process.enumerateModules().find(m => m.name.toLowerCase().includes('01001b300b9be000.exe'));
  if (!exe) throw new Error('runtime exe not found');
  const disp = exe.base.add(G_DISP).readPointer();
  const codeLo = exe.base.add(G_CODE_LO).readU64();
  const off = TARGET.sub(codeLo).toUInt32();
  const slot = disp.add((off >>> 2) * 8);
  const fn = slot.readPointer();
  if (!fn.isNull()) {
    const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
    const exp = mod.findExportByName('snx_module');
    const p = new NativeFunction(exp, 'pointer', [])();
    const nentries = p.add(16).readU32(), ea = p.add(24).readPointer(), ef = p.add(32).readPointer();
    const all = [];
    for (let i = 0; i < nentries; i++) all.push([ef.add(i * 8).readPointer(), ea.add(i * 8).readPointer()]);
    all.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    function near(a) {
      let lo = 0, hi = all.length - 1, best = -1;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (all[mid][0].compare(a) <= 0) { best = mid; lo = mid + 1; } else hi = mid - 1; }
      if (best < 0) return null;
      return {guest: all[best][1].toString(), delta: a.sub(all[best][0]).toString()};
    }
    Interceptor.attach(fn, {
      onEnter(args) {
        const ctx = this.context;
        send({event: 'enter', target: TARGET.toString(), host: fn.toString(),
              x0: ctx.x0.toString(), x1: ctx.x1.toString(), x2: ctx.x2.toString(), x3: ctx.x3.toString(),
              bt: Thread.backtrace(ctx, Backtracer.ACCURATE).slice(0, 12).map(a => ({host: a.toString(), near: near(a)}))});
      },
    });
    send({event: 'hook', target: TARGET.toString(), codeLo: codeLo.toString(), host: fn.toString()});
  } else {
    send({event: 'hook', target: TARGET.toString(), error: 'disp slot empty'});
  }
} catch (e) { send({event: 'error', error: e.message, stack: e.stack}); }
"""


def find_window(pid: int) -> int | None:
    user32 = ctypes.windll.user32
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _):
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(proc(callback), 0)
    return found[0] if found else None


def send_key(hwnd: int, vk: int, scan: int, hold: float = 0.12) -> None:
    user32 = ctypes.windll.user32
    user32.PostMessageW(hwnd, 0x0100, vk, 1 | (scan << 16))
    time.sleep(hold)
    user32.PostMessageW(hwnd, 0x0101, vk, 0xC0000001 | (scan << 16))


KEYS = {"space": (0x20, 0x39), "enter": (0x0D, 0x1C), "escape": (0x1B, 0x01)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--guest", required=True)
    ap.add_argument("--key", choices=sorted(KEYS), default="space")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.pid)
    payload = {"target": args.guest, "g_disp": G_DISP_OFFSET, "code_lo": G_CODE_LO_OFFSET}
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))
    messages: list[dict] = []

    def on_message(message, data):
        p = message.get("payload", {})
        messages.append(p)
        if p.get("event") == "enter":
            print(f"ENTER target={p['target']} x0={p['x0']} x1={p['x1']} x2={p['x2']} x3={p['x3']}")
            for frame in p.get("bt", [])[:10]:
                print("  ", frame.get("host"), frame.get("near"))
        elif p.get("event") in ("hook", "error"):
            print(p)

    script.on("message", on_message)
    script.load()
    time.sleep(1.0)
    hwnd = find_window(args.pid)
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    print(f"sending {args.key} to hwnd={hwnd}")
    if hwnd:
        send_key(hwnd, *KEYS[args.key])
    time.sleep(args.seconds)
    session.detach()


if __name__ == "__main__":
    main()
