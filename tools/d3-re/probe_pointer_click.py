"""Inject one SDL pointer click into the game, without focus or a real cursor.

Coordinates are engine viewport pixels. This exercises SDL's mouse event queue
and the production pointer handler; it does not call the movement implementation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {click(x, y, viewportWidth, viewportHeight) {
  const win = base.add(RVA.sdl_window).readPointer();
  if (win.isNull()) throw new Error('SDL window missing');
  const size = Memory.alloc(8);
  const getSize = new NativeFunction(base.add(RVA.sdl_get_window_size), 'bool',
                                    ['pointer', 'pointer', 'pointer']);
  if (!getSize(win, size, size.add(4))) throw new Error('SDL window size unavailable');
  const width = size.readS32(), height = size.add(4).readS32();
  const getId = new NativeFunction(base.add(RVA.sdl_get_window_id), 'uint', ['pointer']);
  const id = getId(win);
  const push = new NativeFunction(base.add(RVA.sdl_push_event), 'bool', ['pointer']);
  const safe = Memory.alloc(16);
  const getSafe = new NativeFunction(base.add(RVA.backend_window_safe), 'void',
                                     ['pointer', 'pointer', 'pointer', 'pointer']);
  getSafe(safe, safe.add(4), safe.add(8), safe.add(12));
  const area = [0,4,8,12].map(o => safe.add(o).readS32());
  const getDensity = new NativeFunction(base.add(RVA.sdl_pixel_density), 'float', ['pointer']);
  const density = getDensity(win);
  if (!(density > 0 && area[2] > 0 && area[3] > 0)) throw new Error('invalid safe area');
  let dw = area[2], dh = Math.floor(dw * viewportHeight / viewportWidth);
  if (dh > area[3]) { dh = area[3]; dw = Math.floor(dh * viewportWidth / viewportHeight); }
  const dx = area[0] + Math.floor((area[2] - dw) / 2);
  const dy = area[1] + Math.floor((area[3] - dh) / 2);
  const logical = [(dx + x / viewportWidth * dw) / density,
                   (dy + y / viewportHeight * dh) / density];
  const results = [];
  for (const down of [true, false]) {
    const ev = Memory.alloc(128);
    ev.writeByteArray(new Uint8Array(128));
    ev.writeU32(down ? 0x401 : 0x402);
    ev.add(16).writeU32(id);
    ev.add(24).writeU8(1);
    ev.add(25).writeU8(down ? 1 : 0);
    ev.add(26).writeU8(1);
    ev.add(28).writeFloat(logical[0]);
    ev.add(32).writeFloat(logical[1]);
    results.push(push(ev));
  }
  return {windowId:id, windowSize:[width,height], enginePixel:[x,y],
          logicalPixel:logical, pictureRect:[dx,dy,dw,dh], pixelDensity:density,
          down:results[0], up:results[1]};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--y", type=float, required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if not (args.width > 0 and args.height > 0 and
            0 <= args.x < args.width and 0 <= args.y < args.height):
        ap.error("pointer must be inside the viewport")
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.click(args.x, args.y, args.width, args.height)
        result["build"] = build
    finally:
        session.detach()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
