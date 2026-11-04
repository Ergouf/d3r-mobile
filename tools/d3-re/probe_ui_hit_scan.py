"""Scan engine pixels through one widget's native hit test (0x83BB0F0).

Usage:
  python tools/d3-re/probe_ui_hit_scan.py --pid 1234 --obj 5867932544 --region 200,380,500,540 --step 20
"""
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
function scanHits(cpu,req){
  const sp=cpu.add(248).readU64().toNumber(),pixel=sp-0x20000,ref=pixel+0x40;
  const obj=req.obj, vt=u64(obj), pc=u64(vt+0x78);
  const out={obj,vt,pc,region:req.region,step:req.step,hits:[]};
  for(let y=req.region[1]; y<=req.region[3]; y+=req.step)
  for(let x=req.region[0]; x<=req.region[2]; x+=req.step){
    gp(pixel).writeS32(x); gp(pixel+4).writeS32(y);
    gp(ref).writeByteArray(new Uint8Array(32));
    const r=callGuest(cpu,pc,[obj,pixel],ref,null,null);
    const key=gp(ref).readU64().toString();
    if(key!=='18446744073709551615'){
      out.hits.push({x,y,key,ret:r,out:hexBytes(ref,32)});
    }
  }
  return out;
}
"""


def build_js() -> str:
    js = bridge.JS.replace("__CONTEXT__", "null").replace("__FRAME__", "0x80fc310")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "null")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
        "if (req.mode === 'ui-scan') { result = scanHits(cpu,req); } else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--region", required=True, help="x1,y1,x2,y2")
    ap.add_argument("--step", type=int, default=20)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(build_js())
        script.load()
        script.exports_sync.arm({"mode": "ui-scan", "obj": args.obj,
                                 "region": [int(v) for v in args.region.split(",")],
                                 "step": args.step})
        deadline = time.monotonic() + 20
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
    result = data.get("result") or {}
    print("hits", len(result.get("hits", [])))
    for h in result.get("hits", [])[:40]:
        print(h["x"], h["y"], h["key"])


if __name__ == "__main__":
    main()
