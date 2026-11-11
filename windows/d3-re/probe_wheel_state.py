"""Read wheel geometry, current categories and page contents; no guest calls.

All pointers are reacquired each dump. Does not select anything or inject input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida
from find_ui_object import fnv1a64
from ui_text import JS as TEXT_JS
from version import assert_installed, js_consts

SLOTS = ["armleft", "armright", "fingerright", "neck", "fingerleft", "hands",
         "shoulder", "torso", "head", "waist", "legs", "feet", "bracers", "bag"]
PREFIX = "root.normallayer.consoleinventoryring_main.layoutroot.inventoryring."
PAGES = ["root.normallayer.consoleinventoryring_main",
         "root.normallayer.consoleskillselection_main"]
CONTENT = [PAGES[0]+".layoutroot.infopaneltitle",
           PAGES[0]+".layoutroot.inventorylist",
           PAGES[1]+".layoutroot.categorytitle",
           PAGES[1]+".layoutroot.categorydescription"]

JS = js_consts() + TEXT_JS + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function k(a){return gm.add(a).readU64().toString();}
rpc.exports={dump(names){
 const world=q(q(0x914f840)+0x10),manager=q(world+0xb80),map=q(manager);
 const mask=u(map),buckets=q(map+0x10),registry=new Map();
 if(mask>262143)throw new Error('bad UI registry');
 for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n))
   registry.set(k(n+8),q(n+0x10));
 function visible(obj){
  for(let i=0;obj&&i<64;i++){
   if(!(u(obj+0x18)&4))return false;
   const pk=k(obj+0x38);if(pk==='18446744073709551615')return true;
   obj=registry.get(pk);
  }return false;
 }
 function within(obj,ancestor){
  for(let i=0;obj&&i<64;i++){
   if(obj===ancestor)return true;obj=registry.get(k(obj+0x38));
  }return false;
 }
 function item(key,index,name){
  const obj=registry.get(key);if(!obj)return {key,index,name,obj:0};
  return {obj,key,index,name,visible:visible(obj),vt:q(obj),
   rect:[0x88,0x8c,0x90,0x94].map(o=>gm.add(obj+o).readFloat())};
 }
 function nativeWheel(selector,controller=0){
  const data=q(selector),count=q(selector+8),selected=u(selector+0x28),entries=[];
  if(data&&count<=128)for(let i=0;i<count;i++){
    const key=k(data+i*16+8),obj=registry.get(key);
    let h=BigInt(key);for(const ch of '.layoutroot.button')h=BigInt.asUintN(64,(h^BigInt(ch.charCodeAt(0)))*0x100000001b3n);
    const highlight=registry.get(h.toString())||obj;
    const method=highlight?q(q(highlight)+0x138):0;
    let category=null;
    if(controller&&u(controller+0x158)<=4095){
      const mask=u(controller+0x158),buckets=q(controller+0x168),v=BigInt(key);
      const bucket=Number((v^(v>>32n))&BigInt(mask));
      if(buckets)for(let node=q(buckets+bucket*8),guard=0;node&&guard++<64;node=q(node))
        if(k(node+8)===key){category=u(node+0x10);break;}
    }
    entries.push({...item(key,i,names.labels[key]||'native-'+i),angle:gm.add(data+i*16).readFloat(),key,category,
      highlight:highlight?{obj:highlight,method,state:method===0x83911f0?u(highlight+0x464):null}:null});
  }
  const cursorKey=k(selector+0x20),cursor=registry.get(cursorKey),ringKey=k(selector+0x18);
  const ring=registry.get(ringKey);
  return {selector,selected,entries,selectedKey:entries[selected]?.key,
    ring: ring?{obj:ring,vt:q(ring),visible:visible(ring),binding:q(ring+0x48),children:u(ring+0x68)}:null,
    enabled:u(selector+0x2c),rotates:u(selector+0x30),ringKey,
    cursor:{key:cursorKey,obj:cursor||0,visible:!!cursor&&visible(cursor),
      angle:cursor?gm.add(cursor+0x108).readFloat():null}};
 }
 const equipment=q(q(0x9157f58)),skill=q(q(0x9158040)),selector=skill+0x168;
 const ed=names.slots.map((key,index)=>item(key,index,names.slotNames[index]));
 const data=q(selector),count=q(selector+8),sd=[];
 if(data&&count<=32)for(let i=0;i<count;i++){
   const key=k(data+i*16+8);sd.push({...item(key,i,'skill-'+i),angle:gm.add(data+i*16).readFloat()});
 }
 const pages=names.pages.map(key=>{const obj=registry.get(key);return {key,obj,visible:!!obj&&visible(obj)};});
 const texts=[];
 for(const [key,obj] of registry){
  if(!visible(obj)||!UI_TEXT_VTABLES.has(q(obj)))continue;
  const value=readUIText(q(obj+0x398),u(obj+0x3a0));
  if(value.text)texts.push({key,obj,text:value.text,rect:[0x88,0x8c,0x90,0x94].map(o=>gm.add(obj+o).readFloat()),
    page:pages.findIndex(p=>p.obj&&within(obj,p.obj))});
 }
 const nav=q(q(0x9152080)),group=q(nav+0x108);
 const navigationEntries=[];
 if(group&&q(group+8)<=64){const data=q(group);for(let i=0;i<q(group+8);i++)
  navigationEntries.push({index:i,open:q(data+i*0x18),close:q(data+i*0x18+8),enabled:u(data+i*0x18+0x10)});}
 const content=names.content.map(([key,name])=>{
  const obj=registry.get(key);if(!obj)return {name,obj:0};
  let text=null;if(UI_TEXT_VTABLES.has(q(obj)))text=readUIText(q(obj+0x398),u(obj+0x3a0)).text;
  return {name,obj,visible:visible(obj),text,
    rows:q(q(obj)+0xe0)===0x838c6c0?u(obj+0x218):null};
 });
 let groupIndex=null;for(let i=0;i<33;i++)if(group&&q(nav+i*8)===group){groupIndex=i;break;}
 const serviceSpecs={2:['vendor',0x9158028],5:['blacksmith',0x91598b0],6:['jeweler',0x9159948],7:['mystic',0x9153e68]};
 let service=null;
 if(serviceSpecs[groupIndex]){
  const [name,slot]=serviceSpecs[groupIndex],holder=q(slot),controller=holder?q(holder):0;
  if(controller)service={name,group:groupIndex,controller,vt:q(controller),active:u(controller+0x18),
    player:u(controller+0xc),mode:u(controller+0x200),selected:u(controller+0x150),
    nativeWheel:nativeWheel(controller+0xd0,controller)};
 }
 return {groupIndex,pageSelected:group?u(group+0x18):null,pages,texts,content,service,navigationEntries,
   equipment:{controller:equipment,active:u(equipment+0x18),selected:u(equipment+0x150),entries:ed,
     nativeWheel:nativeWheel(equipment+0xd0,equipment)},
   skill:{controller:skill,selected:u(selector+0x28),entries:sd,nativeWheel:nativeWheel(selector),callback:q(0x9158068)},
   runtime:{serial:base.add(RVA.world_serial).readU32(),blocked:base.add(RVA.world_ui_blocked).readU32()}};
}};
"""


def names() -> dict:
    key = lambda n: str(fnv1a64(n.encode()))
    weapons = ['sword','crossbow','dagger','wand','mace','offhand','mighty','staff','axe','fist','bow','flail','scythe']
    armor = ['fingerleft','fingerright','neck','hands','shoulder','torso','head','waist','legs','feet','bracers','bag']
    labels = {key(PREFIX+'button_'+n):n for n in SLOTS}
    for ring, slots in [('blacksmithweaponsring', weapons), ('blacksmitharmorring', armor)]:
        labels.update({key('root.normallayer.consoleinventoryring_main.layoutroot.artisan.'+ring+'.button_'+n):n for n in slots})
    return {"slots": [key(PREFIX + "button_" + n) for n in SLOTS],
            "labels": labels,
            "slotNames": SLOTS, "pages": [key(p) for p in PAGES],
            "content": [[key(p),p] for p in CONTENT]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.dump(names())
    finally:
        session.detach()
    result.update(pid=args.pid, build=build)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), "utf-8")
    print(json.dumps({"group": result["groupIndex"], "page": result["pageSelected"],
                      "equipment": result["equipment"]["selected"],
                      "skill": result["skill"]["selected"], "texts": len(result["texts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
