"""Read live draw/FSR sizes without screenshots, OS input or changing game state.

Private symbols come from the pinned installed EXE. The small g_rp/Surf layout
offsets below correspond to the declarations in gpu/vk/render.c and vk.h.
This hook capture is diagnostic and must not be used as a performance sample.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida
import psutil

import session_driver
import version


JS = r"""
const symbols = SYMBOLS;
const module = Process.getModuleByName('01001B300B9BE000.exe');
const base = module.base;
const groups = {}, fsr = {}, errors = [];
const rp = base.add(symbols.g_rp), scale = base.add(symbols.g_draw_scale);
function shape(p) {
  return {logical:[p.add(8).readU32(),p.add(12).readU32()],
          physical:[p.add(24).readU32(),p.add(28).readU32()]};
}
Interceptor.attach(base.add(symbols.vk_render_draw), {
  onEnter(args) {
    const r = args[0].add(308);
    this.width = r.add(0x202 * 4).readU32();
    this.shader = r.add(0x851 * 4).readU32();
    this.depthState = [0x4B3,0x4BA,0x4E0].map(i=>r.add(i*4).readU32());
  },
  onLeave() {
    if (this.width !== 1280 && this.width !== 1600) return;
    try {
      if (!rp.add(84).readS32()) return;
      const color = rp.readPointer();
      if (color.isNull()) return;
      const c = shape(color);
      if (c.logical[0] !== this.width) return;
      const z = rp.add(64).readPointer();
      const record = {color:c,scale:scale.readFloat(),
        extent:[rp.add(76).readU32(),rp.add(80).readU32()],
        depth:z.isNull()?null:shape(z),shaderOffset:this.shader,depthState:this.depthState};
      const key = JSON.stringify(record);
      if (!groups[key]) groups[key] = {...record,draws:0};
      groups[key].draws++;
    } catch (error) { if (errors.length < 4) errors.push(String(error)); }
  }
});
Interceptor.attach(base.add(symbols.vk_fsr_draw_target), {
  onEnter(args) {
    const rect = args[9], uv = args[3];
    const record = {input:[args[4].toUInt32(),args[5].toUInt32()],
      output:Array.from(new Int32Array(rect.readByteArray(16))),
      uv:Array.from(new Float32Array(uv.readByteArray(16)))};
    const key = JSON.stringify(record);
    if (!fsr[key]) fsr[key] = {...record,draws:0};
    fsr[key].draws++;
  }
});
rpc.exports = {read() { return {groups:Object.values(groups),fsr:Object.values(fsr),errors}; }};
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.seconds <= 5:
        parser.error("seconds must be in (0, 5]")
    build = version.assert_installed()
    identity = session_driver._process_identity(args.pid)
    table = version._symbol_table(version.EXE)
    names = ("g_rp", "g_draw_scale", "vk_render_draw", "vk_fsr_draw_target")
    missing = [name for name in names if name not in table]
    if missing:
        raise SystemExit("missing diagnostic symbols: " + ", ".join(missing))
    symbols = {name: table[name] for name in names}
    session = frida.attach(args.pid)
    try:
        script = session.create_script(JS.replace("SYMBOLS", json.dumps(symbols), 1))
        script.load()
        time.sleep(args.seconds)
        data = script.exports_sync.read()
    finally:
        session.detach()
    if psutil.Process(args.pid).create_time() != identity["create_time"]:
        raise SystemExit("process identity changed during capture")
    report = {"identity": identity, "build": build, "seconds": args.seconds, **data}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"groups": len(data["groups"]), "fsr": data["fsr"],
                      "errors": data["errors"]}, indent=2))
    if data["errors"]:
        raise SystemExit("capture contained read errors")


if __name__ == "__main__":
    main()
