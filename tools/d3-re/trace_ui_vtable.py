#!/usr/bin/env python3
"""Hook the UI object's vtable methods and press a key, to find the event method.

Reads the base UI vtable from the runtime's guest memory (global 0x9150730),
resolves each entry through g_disp, and counts calls. The key is posted after the
hooks are in place; methods that start being called are candidates for the UI
input/event path, and their x0..x3 show the arguments.

Usage:
  python tools/d3-re/trace_ui_vtable.py --pid 34420 --key space --seconds 4
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
VT_GLOBAL = 0x9150730
VT_SLOTS = 24

JS = r"""
const P = PAYLOAD;
try {
  const exe = Process.enumerateModules().find(m => m.name.toLowerCase().includes('01001b300b9be000.exe'));
  const gmem = exe.base.add(P.g_mem).readPointer();
  const disp = exe.base.add(P.g_disp).readPointer();
  const codeLo = exe.base.add(P.code_lo).readU64();
  const vt = gmem.add(P.vt_global).readPointer().toUInt32();
  const entries = [];
  const counters = {};
  const sampled = {};
  for (let i = 0; i < P.slots; i++) {
    let g = 0, host = null;
    try {
      g = gmem.add(vt).add(i * 8).readPointer().toUInt32();
      if (g >= 0x8000000 && g < 0x9b00000) {
        const off = (g - codeLo) >>> 2;
        host = disp.add(off * 8).readPointer();
      }
    } catch (e) { }
    entries.push({i, g, host: host ? host.toString() : null});
    if (host && !host.isNull()) {
      const name = 'vt' + i;
      try {
        Interceptor.attach(host, {
          onEnter(args) {
            counters[name] = (counters[name] || 0) + 1;
            if (sampled[name] === undefined) {
              const c = this.context;
              sampled[name] = {x0: c.x0.toString(), x1: c.x1.toString(), x2: c.x2.toString(), x3: c.x3.toString()};
            }
          },
        });
      } catch (e) { }
    }
  }
  send({event: 'ready', vt: '0x' + vt.toString(16), entries});
  rpc.exports.counts = () => ({counters, sampled});
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
    ap.add_argument("--key", choices=sorted(KEYS), default="space")
    ap.add_argument("--seconds", type=float, default=4.0)
    args = ap.parse_args()

    session = frida.get_local_device().attach(args.pid)
    payload = {"g_mem": G_MEM_OFFSET, "g_disp": G_DISP_OFFSET, "code_lo": G_CODE_LO_OFFSET,
               "vt_global": VT_GLOBAL, "slots": VT_SLOTS}
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))

    def on_message(message, data):
        p = message.get("payload", {})
        if p.get("event") == "ready":
            print(f"vtable=0x{p['vt']} entries={len(p['entries'])}")
            for e in p["entries"]:
                print(f"  slot {e['i']:2d} guest=0x{e['g']:x} host={e['host']}")
        elif p.get("event") == "error":
            print("ERROR", p)

    script.on("message", on_message)
    script.load()
    time.sleep(1.0)
    before = script.exports_sync.counts()["counters"]
    hwnd = find_window(args.pid)
    print(f"sending {args.key} to hwnd={hwnd}")
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        send_key(hwnd, *KEYS[args.key])
    time.sleep(args.seconds)
    after = script.exports_sync.counts()
    counts = after["counters"]
    sampled = after["sampled"]
    print("methods called after the key:")
    for name in sorted(counts, key=lambda n: -(counts[n] - before.get(n, 0))):
        delta = counts[name] - before.get(name, 0)
        if delta:
            print(f"  {name}: {delta}  first={sampled.get(name)}")
    session.detach()


if __name__ == "__main__":
    main()
