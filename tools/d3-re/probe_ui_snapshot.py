"""Read named UI controls, visibility ancestors, rectangles and text buffers."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import frida

from find_ui_object import fnv1a64
from version import assert_installed, js_consts
from ui_text import JS as TEXT_JS

JS = js_consts() + TEXT_JS + r"""
function u64(a){return gm.add(a).readU64().toNumber();}
function u32(a){return gm.add(a).readU32();}
rpc.exports={snapshot(names,includeHidden){
  const world=u64(u64(0x914f840)+0x10),map=u64(u64(world+0xb80)),mask=u32(map),buckets=u64(map+0x10);
  const wanted=new Map(names.map(n=>[n[0],n[1]])),objects=[],registry=new Map();
  if(mask>262143)throw new Error('invalid UI registry');
  for(let b=0;b<=mask;b++)for(let node=u64(buckets+b*8),guard=0;node&&guard++<1024;node=u64(node)){
    const key=gm.add(node+8).readU64().toString();
    registry.set(key,u64(node+0x10));
  }
  for(const [key,obj] of registry){
    if(!wanted.has(key))continue;
    const flags=u32(obj+0x18),ancestors=[],seen=new Set([key]);
    // +0x20 is an intrusive registry link. The real parent is the UIReference
    // key at +0x38 (0x83B7EE0 / 0x83B7540 resolve it through 0x832C9D0).
    let visible=!!(flags&4),parentKey=gm.add(obj+0x38).readU64().toString();
    while(parentKey!=='18446744073709551615'){
      const parent=registry.get(parentKey);
      if(!parent||seen.has(parentKey)||seen.size>=64){visible=false;break;}
      seen.add(parentKey);
      const f=u32(parent+0x18);ancestors.push({obj:parent,flags:f});
      if(!(f&4))visible=false;
      parentKey=gm.add(parent+0x38).readU64().toString();
    }
    if(!includeHidden&&!visible)continue;
    const texts=[],textErrors=[];
    // Only verified text subclasses own a UTF-8 byte string in this slot.
    for(const off of UI_TEXT_VTABLES.has(u64(obj))?[0x398]:[]){const p=u64(obj+off),s=readUIText(p,u32(obj+0x3a0));
      if(s.text)texts.push({offset:off,pointer:p,text:s.text});
      if(s.error)textErrors.push({offset:off,pointer:p,...s});}
    objects.push({name:wanted.get(key),key,obj,vt:u64(obj),flags,visible,ancestors,
      rect:[0x88,0x8c,0x90,0x94].map(o=>gm.add(obj+o).readFloat()),texts,textErrors});
  }
  return {count:u32(map+4),objects};
}};
"""


def names_for(pattern: str) -> list[list[str]]:
    data = Path("out/windows/kbm/b2/runtime_rodata.bin").read_bytes()
    names = set()
    for m in re.finditer(rb"[ -~]{4,300}",data):
        name = m.group().decode("ascii").lower()
        if name.startswith("root.") and re.search(pattern,name,re.I):
            names.add(name)
            parts = name.split(".")
            names.update(".".join(parts[:i]) for i in range(2,len(parts)))
    return [[str(fnv1a64(n.encode())),n] for n in sorted(names)]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid",type=int,required=True)
    ap.add_argument("--match",default="consoleconversation")
    ap.add_argument("--hidden",action="store_true")
    ap.add_argument("--out",type=Path,required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.snapshot(names_for(args.match),args.hidden)
    finally:
        session.detach()
    result["build"] = build
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,ensure_ascii=False),"utf-8")
    for obj in result["objects"]:
        print(obj["name"],obj["visible"],obj["rect"],obj["texts"])


if __name__ == "__main__":
    main()
