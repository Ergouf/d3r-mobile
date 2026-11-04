"""Probe the internal values of the UI hit test for one widget."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_guest_call as bridge
from version import assert_installed

EXTENSION = r"""
function u64(a){return gp(a).readU64().toNumber();}
function u32(a){return gp(a).readU32();}
function probeWidget(cpu,req){
  const sp=cpu.add(248).readU64().toNumber(),buf=sp-0x20000;
  const obj=req.obj, out={obj,vt:u64(obj),flags:u32(obj+0x18)};
  gp(buf).writeByteArray(new Uint8Array(0x80));
  // 0x8398cd0(widget, x8=out)
  out.getRoot=callGuest(cpu,0x8398cd0,[obj],buf,null,null);
  out.rootVal=u64(buf).toString(16);
  // 0x834c300() -> gauges the current UI root/player
  const cur=callGuest(cpu,0x834c300,[],null,null,null);
  out.current=cur.ret;
  const p=cur.ret;
  try{out.currentVal=u64(p).toString(16)}catch(e){out.currentVal='err:'+e.message}
  // point conversion for the requested pixel
  gp(buf+0x40).writeS32(req.pixel[0]); gp(buf+0x44).writeS32(req.pixel[1]);
  out.conv=callGuest(cpu,0x8350bf0,[buf+0x40,buf+0x50],null,null,null);
  out.point=[gp(buf+0x50).readFloat(),gp(buf+0x54).readFloat()];
  // 0x83b7ee0(widget) -> transform pointer
  const xfRes=callGuest(cpu,0x83b7ee0,[obj],null,null,null);
  out.xform=xfRes.ret;
  // rect fields
  out.rect=[0x88,0x8c,0x90,0x94].map(o=>gp(obj+o).readFloat());
  out.local=[0xe0,0xe4,0xe8,0xec].map(o=>gp(obj+o).readFloat());
  out.matrix=[];
  const xf=xfRes.ret;
  if(xf){for(let i=0;i<8;i++){try{out.matrix.push(gp(xf+i*4).readFloat())}catch(e){break}}}
  return out;
}
"""


def build_js() -> str:
    js = bridge.JS.replace("__CONTEXT__", "null").replace("__FRAME__", "0x80fc310")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "null")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
        "if (req.mode === 'ui-probe') { result = probeWidget(cpu,req); } else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--screen", default="320,455")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(build_js())
        script.load()
        script.exports_sync.arm({"mode": "ui-probe", "obj": args.obj,
                                 "pixel": [int(v) for v in args.screen.split(",")]})
        deadline = time.monotonic() + 15
        data = {}
        while time.monotonic() < deadline:
            data = script.exports_sync.result()
            if data.get("result"):
                break
            time.sleep(0.1)
    finally:
        session.detach()
    data["build"] = build
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    print(json.dumps(data.get("result"), indent=1))


if __name__ == "__main__":
    main()
