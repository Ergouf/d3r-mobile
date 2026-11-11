"""Press, drag and release an SDL mouse button in one attach (click-and-hold).

Coordinates are engine viewport pixels. The moves are real SDL motion events, so
the production pointer handler sees a held button with a moving pointer.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
const st = {win: null, id: 0, density: 1, area: [0, 0, 0, 0], w: 1280, h: 720};
function toLogical(x, y, vw, vh) {
  const a = st.area;
  let dw = a[2], dh = Math.floor(dw * vh / vw);
  if (dh > a[3]) { dh = a[3]; dw = Math.floor(dh * vw / vh); }
  const dx = a[0] + Math.floor((a[2] - dw) / 2);
  const dy = a[1] + Math.floor((a[3] - dh) / 2);
  return [(dx + x / vw * dw) / st.density, (dy + y / vh * dh) / st.density];
}
function pushButton(x, y, vw, vh, button, down) {
  const l = toLogical(x, y, vw, vh);
  const push = new NativeFunction(base.add(RVA.sdl_push_event), "bool", ["pointer"]);
  const ev = Memory.alloc(128);
  ev.writeByteArray(new Uint8Array(128));
  ev.writeU32(down ? 0x401 : 0x402);
  ev.add(16).writeU32(st.id);
  ev.add(20).writeU32(1);
  ev.add(24).writeU8(button);
  ev.add(25).writeU8(down ? 1 : 0);
  ev.add(26).writeU8(1);
  ev.add(28).writeFloat(l[0]);
  ev.add(32).writeFloat(l[1]);
  return {logical: l, pushed: push(ev)};
}
function pushMotion(x, y, vw, vh, held) {
  const l = toLogical(x, y, vw, vh);
  const push = new NativeFunction(base.add(RVA.sdl_push_event), "bool", ["pointer"]);
  const ev = Memory.alloc(128);
  ev.writeByteArray(new Uint8Array(128));
  ev.writeU32(0x400);
  ev.add(16).writeU32(st.id);
  ev.add(20).writeU32(1);
  ev.add(24).writeU32(held);
  ev.add(28).writeFloat(l[0]);
  ev.add(32).writeFloat(l[1]);
  ev.add(36).writeFloat(0);
  ev.add(40).writeFloat(0);
  return {engine: [x, y], logical: l, pushed: push(ev)};
}
rpc.exports = {
  init() {
    st.win = base.add(RVA.sdl_window).readPointer();
    if (st.win.isNull()) throw new Error("SDL window missing");
    const size = Memory.alloc(8);
    const getSize = new NativeFunction(base.add(RVA.sdl_get_window_size), "bool", ["pointer", "pointer", "pointer"]);
    if (!getSize(st.win, size, size.add(4))) throw new Error("SDL window size unavailable");
    st.w = size.readS32(); st.h = size.add(4).readS32();
    const getId = new NativeFunction(base.add(RVA.sdl_get_window_id), "uint", ["pointer"]);
    st.id = getId(st.win);
    const safe = Memory.alloc(16);
    const getSafe = new NativeFunction(base.add(RVA.backend_window_safe), "void",
                                       ["pointer", "pointer", "pointer", "pointer"]);
    getSafe(safe, safe.add(4), safe.add(8), safe.add(12));
    st.area = [0, 4, 8, 12].map(o => safe.add(o).readS32());
    const getDensity = new NativeFunction(base.add(RVA.sdl_pixel_density), "float", ["pointer"]);
    st.density = getDensity(st.win);
    return {window: [st.w, st.h], windowId: st.id, pictureRect: st.area, density: st.density};
  },
  down(x, y, vw, vh, button) { return pushButton(x, y, vw, vh, button, true); },
  move(x, y, vw, vh, held) { return pushMotion(x, y, vw, vh, held); },
  up(x, y, vw, vh, button) { return pushButton(x, y, vw, vh, button, false); },
};
"""

BUTTONS = {"left": 1, "middle": 2, "right": 3}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--button", choices=tuple(BUTTONS), default="left")
    ap.add_argument("--from", dest="start", required=True, help="x,y engine pixels")
    ap.add_argument("--to", dest="end", help="x,y engine pixels; omit for a plain press")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--interval-ms", type=int, default=110)
    ap.add_argument("--dwell-ms", type=int, default=250)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.steps < 0 or args.interval_ms < 0 or args.dwell_ms < 0:
        ap.error("steps and delays must not be negative")
    sx, sy = (float(v) for v in args.start.split(","))
    ex, ey = (float(v) for v in (args.end or args.start).split(","))
    for x, y in ((sx, sy), (ex, ey)):
        if not (0 <= x < args.width and 0 <= y < args.height):
            ap.error("pointer must be inside the viewport")
    build = assert_installed()
    button = BUTTONS[args.button]
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        init = script.exports_sync.init()
        events = [script.exports_sync.down(sx, sy, args.width, args.height, button)]
        time.sleep(args.dwell_ms / 1000.0)
        last = (sx, sy)
        for i in range(1, args.steps + 1):
            t = i / args.steps
            last = (sx + (ex - sx) * t, sy + (ey - sy) * t)
            events.append(script.exports_sync.move(last[0], last[1], args.width, args.height, 1))
            time.sleep(args.interval_ms / 1000.0)
        time.sleep(args.dwell_ms / 1000.0)
        events.append(script.exports_sync.up(last[0], last[1], args.width, args.height, button))
    finally:
        session.detach()
    result = {"build": build, "button": args.button, "from": [sx, sy], "to": [ex, ey],
              "steps": args.steps, "interval_ms": args.interval_ms, "dwell_ms": args.dwell_ms,
              "window": init, "events": events}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
