#!/usr/bin/env python3
"""Capture UI widget callback objects when a screen is built.

Hooks the runtime constructor at 0x83a1db0 (stores callbacks at widget +0xa8 /
+0xb0) and prints each widget and the callback objects it received. Run it at
the "press any key" screen and let the script press a key, so the main menu's
widgets are constructed while the hook is in place.

Usage:
  python tools/d3-re/trace_ui_widgets.py --pid 33544 --key space --seconds 6
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import time

import frida

G_MEM_OFFSET = 0x17AEF20
G_DISP_OFFSET = 0x12910E0
G_CODE_LO_OFFSET = 0x17AF028
CTOR = 0x83B70C0

JS = r"""
const P = PAYLOAD;
try {
  const exe = Process.enumerateModules().find(m => m.name.toLowerCase().includes('01001b300b9be000.exe'));
  const gmem = exe.base.add(P.g_mem).readPointer();
  const disp = exe.base.add(P.g_disp).readPointer();
  const codeLo = exe.base.add(P.code_lo).readU64();
  const ctor = P.ctor;
  const off = (ctor - codeLo) >>> 2;
  const host = disp.add(off * 8).readPointer();
  if (host.isNull()) {
    send({event: 'error', error: 'disp slot is empty for 0x' + ctor.toString(16) + ' (not an AOT entry)'});
  } else {
  function readPtr(obj, o) { try { return obj.add(o).readPointer(); } catch (e) { return null; } }
  function readVt(p) { try { return gmem.add(p).readPointer(); } catch (e) { return null; } }
  let n = 0;
  Interceptor.attach(host, {
    onEnter(args) { this.obj = args[0]; this.cfg = args[2]; },
    onLeave(ret) {
      if (n++ > 400) return;
      const o = this.obj;
      const a8 = readPtr(o, 0xa8), b0 = readPtr(o, 0xb0);
      const rec = {obj: o.toString(), cfg: this.cfg.toString(), a8: a8 ? a8.toString() : null, b0: b0 ? b0.toString() : null};
      if (a8) { rec.a8vt = readVt(a8) ? readVt(a8).toString() : null; }
      if (b0) { rec.b0vt = readVt(b0) ? readVt(b0).toString() : null; }
      send({event: 'widget', rec});
    },
  });
  send({event: 'ready', ctor: '0x' + ctor.toString(16), host: host.toString()});
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


KEYS = {"space": (0x20, 0x39), "enter": (0x0D, 0x1C), "escape": (0x1B, 0x01), "none": None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--key", choices=sorted(KEYS), default="none")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--max", type=int, default=30)
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.pid)
    payload = {"g_mem": G_MEM_OFFSET, "g_disp": G_DISP_OFFSET, "code_lo": G_CODE_LO_OFFSET, "ctor": CTOR}
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))
    widgets: list[dict] = []

    def on_message(message, data):
        p = message.get("payload", {})
        if p.get("event") == "widget":
            widgets.append(p["rec"])
        elif p.get("event") in ("ready", "error"):
            print(p)

    script.on("message", on_message)
    script.load()
    time.sleep(1.0)
    hwnd = find_window(args.pid)
    print(f"sending {args.key} to hwnd={hwnd}")
    if hwnd and KEYS[args.key]:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        send_key(hwnd, *KEYS[args.key])
    time.sleep(args.seconds)
    print(f"widgets: {len(widgets)}")
    for w in widgets[:args.max]:
        print(w)
    session.detach()


if __name__ == "__main__":
    main()
