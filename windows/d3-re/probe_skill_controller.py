"""Read the live skill-page controller without changing game state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts


JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports={read(){
  const holder=q(0x9158040), controller=q(holder), vt=q(controller);
  const words=[];
  for(let off=0;off<0x280;off+=4){
    try {words.push({off,value:u(controller+off)});}
    catch(e){words.push({off,error:String(e)});}
  }
  const selectors=[0x168,0x1a4].map(off=>{
    const a=controller+off, data=q(a), count=q(a+8), selected=u(a+0x28);
    const entries=[];
    if(count<=32 && data) for(let i=0;i<count;i++)
      entries.push({index:i,angle:gm.add(data+i*16).readFloat(),key:gm.add(data+i*16+8).readU64().toString()});
    return {off,data,count,selected,entries};
  });
  return {holder,controller,vt,words,selectors};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.read()
    finally:
        session.detach()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("controller", hex(result["controller"]), "vt", hex(result["vt"]))
    print([(hex(x["off"]), hex(x.get("value", 0))) for x in result["words"]
           if x.get("value", 0) not in (0, 0xAAAAAAAA, 0xFFFFFFFF)])
    for selector in result["selectors"]:
        print("selector", hex(selector["off"]), selector["selected"],
              [(e["index"], e["key"]) for e in selector["entries"]])


if __name__ == "__main__":
    main()
