"""Dump the live game UI registry: object, key, flags, parent, rect and text.

The registry is the hash map at *(*(*(0x914f840)+0x10)+0xb80): mask at +0,
count at +4, bucket array at +0x10; a node is {next, key, object}.  Each object
keeps its parent UIReference key at +0x38, flags at +0x18 (bit 2 = visible) and a text
pointer at +0x398 in the two verified UTF-8 label/button classes; +0x3A0
is byte capacity, not text length. Unknown classes are not decoded.

Usage:
  python windows/d3-re/probe_ui_tree.py --pid 1234 --visible --out ui.json
  python windows/d3-re/probe_ui_tree.py --pid 1234 --text 凯恩
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import frida

from version import assert_installed, js_consts
from ui_text import JS as TEXT_JS

JS = js_consts() + TEXT_JS + r"""
function rd64(a){return gm.add(a).readU64().toNumber();}
function rd32(a){return gm.add(a).readU32();}
function rdf(a){return gm.add(a).readFloat();}
rpc.exports={dump(wantText, visibleOnly){
  const p1=rd64(0x914f840), p2=rd64(p1+0x10), map=rd64(rd64(p2+0xb80));
  const mask=rd32(map), count=rd32(map+4), buckets=rd64(map+0x10);
  const out={count, mask, items:[]},registry=new Map();
  if(mask>262143) throw new Error('invalid UI registry mask '+mask);
  for(let b=0;b<=mask;b++)for(let node=rd64(buckets+b*8),guard=0;node&&guard++<1024;node=rd64(node)){
    const key=gm.add(node+8).readU64().toString(), obj=rd64(node+0x10);
    registry.set(key,obj);
  }
  for(const [key,obj] of registry){
    if(!obj) continue;
    const flags=rd32(obj+0x18),parentKey=gm.add(obj+0x38).readU64().toString();
    let visible=!!(flags&4),upKey=parentKey,depth=0,chain=[],seen=new Set([key]);
    while(upKey!=='18446744073709551615'){
      const up=registry.get(upKey);
      if(!up||seen.has(upKey)||++depth>=64){visible=false;break;}
      seen.add(upKey);
      const f=rd32(up+0x18); chain.push({obj:up, flags:f});
      if(!(f&4)) visible=false;
      upKey=gm.add(up+0x38).readU64().toString();
    }
    if(visibleOnly && !visible) continue;
    const rect=[0xe0,0xe4,0xe8,0xec].map(o=>rdf(obj+o));
    const rect2=[0x88,0x8c,0x90,0x94].map(o=>rdf(obj+o));
    const textValue=UI_TEXT_VTABLES.has(rd64(obj))?readUIText(rd64(obj+0x398),rd32(obj+0x3a0)):null;
    const text=textValue?textValue.text:null;
    if(wantText && (!text || text.indexOf(wantText)<0)) continue;
    let cbA=0;try{const callbacks=rd64(obj+0x118);
      if(callbacks>=0x130000000&&callbacks<0x180000000)cbA=rd64(callbacks+0x20);
    }catch(e){}
    out.items.push({obj,key,vt:rd64(obj),flags,parent:registry.get(parentKey)||0,parentKey,visible,depth,
                    rect,rect2,text,hitMode:rd32(obj+0x1b0),enabled:rd32(obj+0x1b8),
                    cbA,textError:textValue&&textValue.error?textValue:null});
  }
  return out;
}};
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--visible", action="store_true")
    ap.add_argument("--text")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.dump(args.text, args.visible)
    finally:
        session.detach()
    result["build"] = build
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    items = result["items"]
    print(f"registry {result['count']} objects, {len(items)} listed")
    for it in sorted(items, key=lambda i: (i["rect"][1] or 0, i["rect"][0] or 0)):
        r = it["rect"]
        if any(v is None for v in r):
            continue
        print(f"obj={it['obj']:>11} key={it['key']:>20} vis={int(it['visible'])} "
              f"rect=({r[0]:8.1f},{r[1]:8.1f}) {r[2]:7.1f}x{r[3]:6.1f} "
              f"text={it['text'] or ''}")


if __name__ == "__main__":
    main()
