"""Inject one SDL mouse motion event (no focus, no real cursor)."""
from __future__ import annotations

import argparse
import json

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {move(x, y) {
  const win = base.add(RVA.sdl_window).readPointer();
  if (win.isNull()) throw new Error('SDL window missing');
  const getId = new NativeFunction(base.add(RVA.sdl_get_window_id), 'uint', ['pointer']);
  const id = getId(win);
  const ev = Memory.alloc(128);
  ev.writeByteArray(new Uint8Array(128));
  ev.writeU32(0x400);          /* SDL_EVENT_MOUSE_MOTION */
  ev.add(16).writeU32(id);
  ev.add(20).writeU32(1);      /* which: the mouse */
  ev.add(28).writeFloat(x);
  ev.add(32).writeFloat(y);
  const push = new NativeFunction(base.add(RVA.sdl_push_event), 'bool', ['pointer']);
  return {pushed: push(ev), windowId: id, x, y};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--y", type=float, required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.move(args.x, args.y)
    finally:
        session.detach()
    result["build"] = build
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
