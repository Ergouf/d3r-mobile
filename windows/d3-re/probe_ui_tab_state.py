"""Read character pages, active navigation group, vendor mode and subscribers.

No input, guest calls, or guest memory writes. Run separately from other
Frida probes. Object words are diagnostic data, not a selected-tab heuristic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from find_ui_object import fnv1a64
from version import assert_installed, js_consts

PAGE_NAMES = [
    "consoleinventoryring_main", "consoleskillselection_main",
    "consoleparagon_main", "consoleparty_main", "consolejournal_main",
]

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function key(a){return gm.add(a).readU64().toString();}
function rect(a){return [0x88,0x8c,0x90,0x94].map(o=>gm.add(a+o).readFloat());}
rpc.exports={dump(names){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10), registry=new Map();
  if(mask>262143)throw new Error('invalid registry');
  for(let b=0;b<=mask;b++)for(let node=q(buckets+b*8),guard=0;node&&guard++<1024;node=q(node))
    registry.set(key(node+8),q(node+0x10));
  function visible(obj){
    const seen=new Set();
    for(let i=0;obj&&i<64;i++){
      if(seen.has(obj)||!(u(obj+0x18)&4))return false;
      seen.add(obj);
      const parentKey=key(obj+0x38);
      if(parentKey==='18446744073709551615')return true;
      obj=registry.get(parentKey);
    }
    return false;
  }
  function object(obj,words){
    const vt=q(obj), parentKey=key(obj+0x38), fields=[];
    if(words)for(let off=0;off<0x600;off+=8){
      try{fields.push({off,hex:'0x'+gm.add(obj+off).readU64().toString(16)});}catch(e){break;}
    }
    return {obj,vt,key:key(obj+0x30),parentKey,parent:registry.get(parentKey)||0,
      flags:u(obj+0x18),visible:visible(obj),rect:rect(obj),fields};
  }
  const pages=names.map(([k,name])=>{
    const obj=registry.get(k);
    return obj?{name,...object(obj,false)}:{name,obj:0};
  });
  const tabs=[], parents=new Map();
  for(const obj of registry.values()){
    if(q(obj)!==0x90abb48||!visible(obj))continue;
    const r=rect(obj);
    if(r[1]<38||r[1]>=64||r[2]-r[0]<150||r[2]-r[0]>162||r[3]-r[1]<20||r[3]-r[1]>28)continue;
    const t=object(obj,true); tabs.push(t);
    if(t.parent)parents.set(t.parent,object(t.parent,true));
  }
  const subscribers=[], subs=q(manager+0x10), data=q(subs), count=u(subs+8);
  if(count>1024)throw new Error('invalid subscribers');
  for(let i=0;i<count;i++){
    const obj=q(data+i*8);
    if(!obj)continue;
    const item=object(obj,false); item.callbacks=[];
    try{
      if(item.vt===0x90ad218){
        item.action=u(obj+0x40); item.actionCallback=q(obj+0x68);
        subscribers.push(item); continue;
      }
      const table=q(obj+0x118);
      item.table=table;
      if(table)for(let off=0;off<=0xa0;off+=8){
        const pc=q(table+off);
        if(pc>=codeLo&&pc<codeHi&&pc%4===0)item.callbacks.push({off,pc});
      }
    }catch(e){item.callbackError=String(e);}
    subscribers.push(item);
  }
  const navigation=q(q(0x9152080)), group=q(navigation+0x108), entries=[];
  if(group){
    const data=q(group), count=u(group+8);
    if(count>64)throw new Error('invalid navigation group');
    for(let i=0;i<count;i++)entries.push({index:i,open:q(data+i*0x18),close:q(data+i*0x18+8),enabled:u(data+i*0x18+0x10)});
  }
  let groupIndex=null;
  for(let i=0;i<33;i++)if(group&&q(navigation+i*8)===group){groupIndex=i;break;}
  const controller=q(q(0x9158028));
  const vendor=controller?{controller,vt:q(controller),active:u(controller+0x18),mode:u(controller+0x200)}:null;
  const smithHolder=q(0x91598b0), smith=smithHolder?q(smithHolder):0;
  const blacksmith=smith?{controller:smith,vt:q(smith),active:u(smith+0x18),mode:u(smith+0x200)}:null;
  const jewelerHolder=q(0x9159948), jewelerController=jewelerHolder?q(jewelerHolder):0;
  const jeweler=jewelerController?{controller:jewelerController,vt:q(jewelerController),active:u(jewelerController+0x18),mode:u(jewelerController+0x200)}:null;
  const mysticHolder=q(0x9153e68), mysticController=mysticHolder?q(mysticHolder):0;
  const mystic=mysticController?{controller:mysticController,vt:q(mysticController),active:u(mysticController+0x18),mode:u(mysticController+0x200)}:null;
  return {manager,map,navigation,group,groupIndex,player:group?u(group+0x1c):null,
    selected:group?u(group+0x18):null,entries,vendor,blacksmith,jeweler,mystic,
    pages,tabs:tabs.sort((a,b)=>a.rect[0]-b.rect[0]),parents:[...parents.values()],subscribers};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    names = [[str(fnv1a64(("root.normallayer." + n).encode())), n] for n in PAGE_NAMES]
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.dump(names)
    finally:
        session.detach()
    result.update(pid=args.pid, build=build)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("navigation", hex(result["navigation"]), "group", hex(result["group"]),
          "index", result["groupIndex"], "selected", result["selected"],
          "vendor", result["vendor"], "blacksmith", result["blacksmith"], "entries", result["entries"])
    for page in result["pages"]:
        print(page["name"], hex(page["obj"]), page.get("visible"))
    for item in result["tabs"]:
        print("tab", hex(item["obj"]), item["rect"], "parent", hex(item["parent"]), "flags", hex(item["flags"]))
    for item in result["subscribers"]:
        print("subscriber", hex(item["obj"]), hex(item["vt"]), "visible", item["visible"],
              "action", item.get("action"), "actionCallback", hex(item.get("actionCallback", 0)),
              "callbacks", [(hex(c["off"]), hex(c["pc"])) for c in item["callbacks"]])


if __name__ == "__main__":
    main()
