"""Find the game UI widget at an engine pixel and optionally run its A callback.

Widgets store their final screen rectangle at +0x88 (x1, y1, x2, y2 floats,
engine 1280x720 pixels), their visibility in bit 2 of the flags at +0x18, their
parent at +0x20, their name key at +0x30 and their per-button callback table at
+0x118 (A at +0x118 + 0*8 + 0x20).

Usage:
  python windows/d3-re/probe_ui_hit.py --pid 1234 --screen 320,455
  python windows/d3-re/probe_ui_hit.py --pid 1234 --screen 320,455 --invoke
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function textAt(p){
  if(!p || p<0x130000000 || p>0x180000000)return null;
  try {
    const bytes=new Uint8Array(gm.add(p).readByteArray(256));
    let n=bytes.indexOf(0);if(n<0)n=256;
    if(n>=2) {
      try {const s=gm.add(p).readUtf8String(n);
        if(s.length>1 && !/[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]/.test(s) && /[\u4e00-\u9fffA-Za-z]/.test(s))return s;
      }catch(e){}
    }
  } catch(e){}
  return null;
}
rpc.exports={
  hit(px, py){
    const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
    const mask=u(map), count=u(map+4), buckets=q(map+0x10);
    const hits=[];
    for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n)){
      const key=gm.add(n+8).readU64().toString(), obj=q(n+0x10);
      if(!obj) continue;
      let flags=u(obj+0x18);
      let visible=!!(flags&4), up=q(obj+0x20), depth=0;
      while(up && depth++<64){const f2=u(up+0x18); if(!(f2&4)) visible=false; up=q(up+0x20);}
      if(!visible) continue;
      const r=[f(obj+0x88),f(obj+0x8c),f(obj+0x90),f(obj+0x94)];
      if(!(r[2]>r[0] && r[3]>r[1])) continue;
      if(px<r[0]||px>r[2]||py<r[1]||py>r[3]) continue;
      const table=q(obj+0x118);
      let a=0, b0=0, c0=0, d0=0;
      if(table){
        try{a=q(table+0x20);}catch(e){}
        try{b0=q(table+0x140);}catch(e){}
        try{c0=q(table+0x148);}catch(e){}
        try{d0=q(table+0x50);}catch(e){}
      }
      hits.push({obj,key,flags,depth,rect:r,cbA:a,cb140:b0,cb148:c0,cb50:d0,
                 text:textAt(q(obj+0x398))});
    }
    hits.sort((x,y)=>((x.rect[2]-x.rect[0])*(x.rect[3]-x.rect[1]))-((y.rect[2]-y.rect[0])*(y.rect[3]-y.rect[1])));
    return {px,py,total:count,hits};
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--screen", required=True)
    ap.add_argument("--invoke", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    px, py = (float(v) for v in args.screen.split(","))
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.hit(px, py, args.invoke)
    finally:
        session.detach()
    result["build"] = build
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("total", result["total"], "hits", len(result["hits"]))
    for h in result["hits"][:12]:
        r = h["rect"]
        print(f"obj={h['obj']} depth={h['depth']} rect=({r[0]:.1f},{r[1]:.1f})-({r[2]:.1f},{r[3]:.1f}) "
              f"cbA={h['cbA']:#x} cb50={h['cb50']:#x} text={h['text']!r}")
    if "invoked" in result:
        print("invoked", result["invoked"])


if __name__ == "__main__":
    main()
