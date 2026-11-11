"""Print a UI object's parent chain (+0x38) for ABI diagnosis."""
from __future__ import annotations

import argparse
import json

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
rpc.exports={chain(obj){
  const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
  const mask=u(map), buckets=q(map+0x10), objects=new Map();
  for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n))
    objects.set(gm.add(n+8).readU64().toString(),q(n+0x10));
  const out=[];let o=obj;
  for(let i=0;i<16&&o;i++){
    const key=gm.add(o+0x30).readU64().toString();
    const rect=[0x88,0x8c,0x90,0x94].map(x=>f(o+x));
    const parentKey=gm.add(o+0x38).readU64().toString();
    out.push({obj:o,key,flags:u(o+0x18),vt:q(o),table:q(o+0x118),
      rect,registered:objects.get(key),parentKey,parent:objects.get(parentKey)});
    o=out[out.length-1].parent;
  }
  return out;
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.chain(args.obj)
    finally:
        session.detach()
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
