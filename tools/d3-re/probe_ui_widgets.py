"""Dump visible UI widgets with rect candidates at +0x78 and +0x88."""
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
    const bytes=new Uint8Array(gm.add(p).readByteArray(512));
    let n=bytes.indexOf(0);if(n<0)n=512;
    if(n>=2) {
      try {const s=gm.add(p).readUtf8String(n);
        if(s.length>1 && !/[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]/.test(s) && /[\u4e00-\u9fffA-Za-z]/.test(s))return s;
      }catch(e){}
    }
  } catch(e){}
  return null;
}
rpc.exports={dump(){
  const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
  const mask=u(map), count=u(map+4), buckets=q(map+0x10);
  const items=[];
  for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n)){
    const key=gm.add(n+8).readU64().toString(), obj=q(n+0x10);
    if(!obj) continue;
    const flags=u(obj+0x18), parent=q(obj+0x20);
    let visible=!!(flags&4), up=parent, depth=0;
    while(up && depth++<64){const f2=u(up+0x18); if(!(f2&4)) visible=false; up=q(up+0x20);}
    const r78=[0x78,0x7c,0x80,0x84].map(o=>f(obj+o));
    const r88=[0x88,0x8c,0x90,0x94].map(o=>f(obj+o));
    const rE0=[0xe0,0xe4,0xe8,0xec].map(o=>f(obj+o));
    items.push({obj,key,flags,parent,visible,depth,r78,r88,rE0,text:textAt(q(obj+0x398))});
  }
  return {count,mask,items};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.dump()
    finally:
        session.detach()
    result["build"] = build
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("count", result["count"], "items", len(result["items"]))


if __name__ == "__main__":
    main()
