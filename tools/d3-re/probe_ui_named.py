"""Report whether named UI paths exist in the live registry.

The `visible` column is the static flags&4 / parent-chain state, not the game's
current display state; use identical before/after dumps or absent paths as the
evidence for a dialog/menu appearing or disappearing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

MASK64 = (1 << 64) - 1


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in data:
        h = ((h ^ c) * 0x100000001B3) & MASK64
    return h


JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
rpc.exports={dump(keys, names){
  const want=new Set(keys);
  const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
  const mask=u(map), buckets=q(map+0x10);
  if(mask>262143)throw new Error('invalid UI map');
  const objects=new Map();
  for(let b=0;b<=mask;b++){
    let node; try{node=q(buckets+b*8)}catch(e){continue}
    for(let g=0;node&&g++<1024;node=q(node)){
      let k,obj;
      try{k=gm.add(node+8).readU64().toString();obj=q(node+0x10)}catch(e){continue}
      if(obj)objects.set(k,obj);
    }
  }
  function visible(obj){
    let o=obj;
    for(let i=0;i<64&&o;i++){
      let fl,pk;
      try{fl=u(o+0x18);pk=gm.add(o+0x38).readU64().toString()}catch(e){return false}
      if(!(fl&4))return false;
      if(pk==='18446744073709551615')return true;
      o=objects.get(pk);
    }
    return false;
  }
  const out=[];
  for(const [k,obj] of objects){
    if(!want.has(k))continue;
    let flags,rect,parent;
    try{flags=u(obj+0x18);rect=[0x88,0x8c,0x90,0x94].map(o=>f(obj+o));parent=gm.add(obj+0x38).readU64().toString()}catch(e){continue}
    out.push({key:k,obj,flags,visible:visible(obj),rect,parent});
  }
  return {count:objects.size,items:out,
    pairs:keys.map((k,i)=>({key:k,name:names[i]}))};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--names", required=True, help="comma-separated UI paths")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    keys = [str(fnv1a64(n.lower().encode())) for n in names]
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.dump(keys, names)
    finally:
        session.detach()
    result["build"] = build
    result["names"] = names
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    by_key = {i["key"]: i for i in result["items"]}
    for name, key in zip(names, keys):
        it = by_key.get(key)
        if not it:
            print(f"{name}: absent")
        else:
            r = it["rect"]
            print(f"{name}: visible={it['visible']} flags={it['flags']:x} rect={r}")


if __name__ == "__main__":
    main()
