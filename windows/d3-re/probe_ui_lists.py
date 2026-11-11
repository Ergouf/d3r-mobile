"""List live UI list widgets (vtable+0xE0 == 0x838C6C0) with rects."""
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
rpc.exports={dump(){
  const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
  const mask=u(map), count=u(map+4), buckets=q(map+0x10);
  const objects=new Map();
  for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n)){
    const key=gm.add(n+8).readU64().toString(), obj=q(n+0x10);
    if(obj) objects.set(key,obj);
  }
  function visible(obj){
    let o=obj;
    for(let i=0;i<64&&o;i++){
      let flags; try{flags=u(o+0x18)}catch(e){return false}
      if(!(flags&4))return false;
      const pk=gm.add(o+0x38).readU64().toString();
      if(pk==='18446744073709551615')return true;
      o=objects.get(pk);
    }
    return false;
  }
  const items=[];
  for(const [key,obj] of objects){
    let vt; try{vt=q(obj)}catch(e){continue}
    let entry=0; try{entry=q(vt+0xe0)}catch(e){}
    if(entry!==0x838c6c0) continue;
    const rect=[0x88,0x8c,0x90,0x94].map(o=>f(obj+o));
    items.push({obj,key,vt,flags:u(obj+0x18),visible:visible(obj),rect,
      rows:u(obj+0x218),page:gm.add(obj+0x1e4).readS32()});
  }
  return {count,items};
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
    print("lists", len(result["items"]))
    for i in result["items"]:
        if not i["visible"]:
            continue
        r = i["rect"]
        if not all(isinstance(v, (int, float)) for v in r):
            continue
        print(f"obj={i['obj']} flags={i['flags']:x} rect=({r[0]:.0f},{r[1]:.0f})-({r[2]:.0f},{r[3]:.0f}) rows={i['rows']} page={i['page']}")


if __name__ == "__main__":
    main()
