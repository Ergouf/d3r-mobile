"""Find UI widgets that own a localized text pointer (UTF-16LE or UTF-8).

Usage:
  python tools/d3-re/probe_ui_text_widget.py --pid 1234 --text 升级储藏箱
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
function gp(a){return gm.add(a);}
rpc.exports={find(utf8hex, utf16hex){
  const pats=[utf8hex, utf16hex];
  const found=[];
  for(const pat of pats){
    for(const r of Process.enumerateRanges('rw-')){
      if(found.length>=12) break;
      try{
        for(const m of Memory.scanSync(r.base,r.size,pat)){
          if(found.length>=12) break;
          found.push(m.address);
        }
      }catch(e){}
    }
  }
  const p1=q(0x914f840), p2=q(p1+0x10), map=q(q(p2+0xb80));
  const mask=u(map), count=u(map+4), buckets=q(map+0x10);
  const out={matches:found.map(a=>a.toString()),objects:[]};
  for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n)){
    const key=gm.add(n+8).readU64().toString(), obj=q(n+0x10);
    if(!obj) continue;
    for(let off=0;off<0x600;off+=8){
      let v; try{v=q(obj+off)}catch(e){continue}
      if(!v) continue;
      let host; try{host=gp(v)}catch(e){continue}
      for(const m of found){
        if(host.compare(m)===0){
          let cbA=0;
          try{const t=q(obj+0x118); if(t)cbA=q(t+0x20);}catch(e){}
          out.objects.push({obj,key,off,
            flags:u(obj+0x18),
            rect:[f(obj+0x88),f(obj+0x8c),f(obj+0x90),f(obj+0x94)],
            local:[f(obj+0xe0),f(obj+0xe4),f(obj+0xe8),f(obj+0xec)],
            cbA,
            match:m.toString()});
        }
      }
    }
  }
  return out;
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    text = args.text
    utf8 = text.encode("utf-8").hex()
    utf16 = text.encode("utf-16le").hex()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.find(utf8, utf16)
    finally:
        session.detach()
    result["build"] = build
    result["text"] = text
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("matches", result["matches"], "objects", len(result["objects"]))
    for o in result["objects"]:
        print(o)


if __name__ == "__main__":
    main()
