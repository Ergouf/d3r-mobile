"""Hold a movement key as short SDL pulses inside one attach.

The world-click path can stall on scenery; short WASD pulses let a script
place the character against walls without a real cursor or window focus.
Usage: python tools/d3-re/probe_walk_hold.py --pid 1234 --key d --pulses 12
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frida
from version import assert_installed, js_consts

KEYS = {"w": (26, 119), "a": (4, 97), "s": (22, 115), "d": (7, 100)}
JS = js_consts() + r"""
rpc.exports={key(scan,keycode,down){
  const win=base.add(RVA.sdl_window).readPointer();
  const id=new NativeFunction(base.add(RVA.sdl_get_window_id),'uint',['pointer'])(win);
  const push=new NativeFunction(base.add(RVA.sdl_push_event),'bool',['pointer']);
  const e=Memory.alloc(128);e.writeByteArray(new Uint8Array(128));
  e.writeU32(down?0x300:0x301);e.add(16).writeU32(id);
  e.add(24).writeU32(scan);e.add(28).writeU32(keycode);e.add(36).writeU8(down?1:0);
  return push(e);
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--key", choices=tuple(KEYS), required=True)
    ap.add_argument("--pulses", type=int, default=8)
    ap.add_argument("--hold", type=float, default=0.4)
    args = ap.parse_args()
    scan, code = KEYS[args.key]
    build = assert_installed()
    session = frida.attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        for _ in range(args.pulses):
            script.exports_sync.key(scan, code, True)
            time.sleep(args.hold)
            script.exports_sync.key(scan, code, False)
            time.sleep(0.15)
    finally:
        session.detach()
    print(json.dumps({"build": build, "key": args.key,
                      "pulses": args.pulses, "hold": args.hold}))


if __name__ == "__main__":
    main()
