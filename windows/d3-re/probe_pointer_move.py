"""Inject one SDL motion; --engine uses viewport pixels with DPI/bars removed."""
from __future__ import annotations

import argparse
import json

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {move(x, y, viewportWidth, viewportHeight) {
  const win = base.add(RVA.sdl_window).readPointer();
  if (win.isNull()) throw new Error('SDL window missing');
  const getId = new NativeFunction(base.add(RVA.sdl_get_window_id), 'uint', ['pointer']);
  const id = getId(win);
  const input = [x,y];
  if (viewportWidth) {
    const safe = Memory.alloc(16);
    new NativeFunction(base.add(RVA.backend_window_safe), 'void',
      ['pointer','pointer','pointer','pointer'])(safe,safe.add(4),safe.add(8),safe.add(12));
    const area = [0,4,8,12].map(o=>safe.add(o).readS32());
    const density = new NativeFunction(base.add(RVA.sdl_pixel_density),'float',['pointer'])(win);
    if (!(density>0 && area[2]>0 && area[3]>0)) throw new Error('invalid picture area');
    let dw=area[2],dh=Math.floor(dw*viewportHeight/viewportWidth);
    if(dh>area[3]){dh=area[3];dw=Math.floor(dh*viewportWidth/viewportHeight);}
    x=(area[0]+Math.floor((area[2]-dw)/2)+x/viewportWidth*dw)/density;
    y=(area[1]+Math.floor((area[3]-dh)/2)+y/viewportHeight*dh)/density;
  }
  const ev = Memory.alloc(128);
  ev.writeByteArray(new Uint8Array(128));
  ev.writeU32(0x400);          /* SDL_EVENT_MOUSE_MOTION */
  ev.add(16).writeU32(id);
  ev.add(20).writeU32(1);      /* which: the mouse */
  ev.add(28).writeFloat(x);
  ev.add(32).writeFloat(y);
  const push = new NativeFunction(base.add(RVA.sdl_push_event), 'bool', ['pointer']);
  return {pushed: push(ev), windowId: id, x, y, input,
          coordinates:viewportWidth?'engine':'SDL logical'};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--x", type=float, required=True)
    ap.add_argument("--y", type=float, required=True)
    ap.add_argument("--engine", action="store_true", help="x/y in engine viewport pixels")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()
    import math
    if not all(math.isfinite(v) for v in (args.x,args.y)):
        ap.error("coordinates must be finite")
    if args.engine and not (args.width>0 and args.height>0 and
                           0<=args.x<args.width and 0<=args.y<args.height):
        ap.error("engine motion must be inside the viewport")
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.move(args.x, args.y,
                                          args.width if args.engine else 0,args.height)
    finally:
        session.detach()
    result["build"] = build
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
