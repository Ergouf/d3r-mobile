"""Snapshot UI registry fields for focus diffing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports={dump(){
  const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
  const mask=u(map), count=u(map+4), buckets=q(map+0x10);
  const items=[];
  for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n)){
    const key=gm.add(n+8).readU64().toString(), obj=q(n+0x10);
    if(!obj) continue;
    const fields={};
    for(const off of [0x18,0x30,0x38,0xa0,0xa4,0xac,0xb0,0xb4,0xb8,0x1b0,0x1b4,0x118]){
      try{fields[off]=q(obj+off).toString(16)}catch(e){}
    }
    items.push({key,obj,fields});
  }
  return {count,items};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result), encoding="utf-8")
    print("count", result["count"], "items", len(result["items"]))


if __name__ == "__main__":
    main()
