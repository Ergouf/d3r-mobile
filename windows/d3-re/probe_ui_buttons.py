"""List live UI button widgets and the active UI roots."""
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
  const p1=q(0x914f840), p2=q(p1+0x10), manager=q(p2+0xb80), map=q(manager);
  const mask=u(map), count=u(map+4), buckets=q(map+0x10);
  const objects=new Map(), items=[];
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
  for(const [key,obj] of objects){
    let vt; try{vt=q(obj)}catch(e){continue}
    let onEvent=0; try{onEvent=q(vt+0x60)}catch(e){}
    if(onEvent!==0x8392410) continue;
    const rect=[0x88,0x8c,0x90,0x94].map(o=>f(obj+o));
    if(!rect.every(Number.isFinite)||rect[2]<=rect[0]||rect[3]<=rect[1]) continue;
    let table=0,cb=0; try{table=q(obj+0x118); if(table)cb=q(table)}catch(e){}
    items.push({obj,key,flags:u(obj+0x18),visible:visible(obj),rect,table,callback:cb,
      parent:gm.add(obj+0x38).readU64().toString()});
  }
  const subs=manager+0x10, entries=q(subs), n=u(subs+8), roots=[];
  for(let i=0;i<n&&i<64;i++){
    const r=q(entries+i*8);
    if(!r)continue;
    roots.push({obj:r,key:gm.add(r+0x30).readU64().toString(),flags:u(r+0x18),
      rect:[0x88,0x8c,0x90,0x94].map(o=>f(r+o))});
  }
  return {count,items,roots,subCount:n};
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
    print("buttons", len(result["items"]), "roots", result["subCount"])
    for i in result["items"]:
        if not i["visible"]:
            continue
        r = i["rect"]
        print(f"obj={i['obj']} cb={i['callback']:#x} rect=({r[0]:.0f},{r[1]:.0f})-({r[2]:.0f},{r[3]:.0f})")
    print("roots:")
    for r in result["roots"]:
        rr = r["rect"]
        print(f"  obj={r['obj']} flags={r['flags']:x} rect=({rr[0]:.0f},{rr[1]:.0f})-({rr[2]:.0f},{rr[3]:.0f})")


if __name__ == "__main__":
    main()
