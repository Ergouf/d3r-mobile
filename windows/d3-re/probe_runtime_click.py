"""Drive the installed runtime's own SDL world click from script injection.

Calls `native_world_click(x, y, w, h, fallback)` exactly as the SDL backend does
for a left button press.  With w/h equal to the engine presentation size and
x/y the fraction of that size, the runtime converts the point 1:1 to engine
pixels.  This is the same code path a real mouse click takes; nothing here uses
Npad, the foreground window or hardware input.

Usage:
  python windows/d3-re/probe_runtime_click.py --pid <pid> --screen 599,147
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {
  click(x, y, w, h, fallback) {
    const fn = new NativeFunction(base.add(RVA.native_world_click), 'int',
      ['float', 'float', 'uint', 'uint', 'uint64']);
    return fn(x, y, w, h, uint64(fallback));
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--screen", required=True, help="engine pixel x,y")
    ap.add_argument("--fallback", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe" for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is no longer running")
    px, py = (float(v) for v in args.screen.split(","))
    session = device.attach(args.pid)
    try:
        script = session.create_script(JS)
        script.on("message", lambda m, d: print("js:", m.get("payload", m), flush=True))
        script.load()
        # engine presentation is 1280x720 in the observed build; the runtime
        # maps the fraction through its own letterbox rectangle
        ret = script.exports_sync.click(px / 1280.0, py / 720.0, 1280, 720, args.fallback)
    finally:
        session.detach()
    data = {"ok": bool(ret), "pid": args.pid, "screen": [px, py], "build": build}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=2), "utf-8")
    print(json.dumps(data))


if __name__ == "__main__":
    main()
