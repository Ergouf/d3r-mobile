"""Read active UI subscribers, native callbacks and list models without input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida
from probe_ui_snapshot import names_for
from version import assert_installed, js_consts

JS=js_consts()+r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function safe(a){try{return q(a);}catch(e){return null;}}
function key(a){return gm.add(a).readU64().toString();}
rpc.exports={read(){
 const manager=q(q(q(0x914f840)+0x10)+0xb80),map=q(manager),mask=u(map),buckets=q(map+0x10);
 const objects=new Map();
 if(mask>262143)throw new Error('invalid UI map');
 for(let b=0;b<=mask;b++)for(let n=q(buckets+b*8),g=0;n&&g++<1024;n=q(n))
  objects.set(key(n+8),q(n+0x10));
 function info(obj){
  const vt=q(obj),isWidget=safe(vt+0xb0)===0x83b81f0;
  const out={obj,key:key(obj+0x30),parent:key(obj+0x38),vt,flags:u(obj+0x18),isWidget,
   methods:[0x50,0x60,0x68,0x70,0x78,0xe0].map(o=>[o,safe(vt+o)])};
  if(isWidget){
   out.rect=[0x88,0x8c,0x90,0x94].map(o=>gm.add(obj+o).readFloat());
   out.hitMode=u(obj+0x1b0);out.children=u(obj+0x68);
   const table=q(obj+0x118);out.table=table;out.callbacks=[];
   if(table)for(let i=0;i<0x150;i+=8){const pc=safe(table+i);if(pc)out.callbacks.push([i,pc]);}
   if(safe(vt+0xe0)===0x838c6c0){
    const model=q(obj+0x258),refs=q(obj+0x210),n=u(obj+0x218);
    out.list={selected:gm.add(obj+0x1e0).readS32(),page:gm.add(obj+0x1e4).readS32(),
     columns:u(obj+0x2a4),rows:[],model,modelVT:model?safe(model):null,
     modelMethods:model?Array.from({length:10},(_,i)=>safe(q(model)+i*8)):[]};
    if(n>4096)throw new Error('invalid rows');
    for(let i=0;i<n;i++){const k=key(refs+i*8),row=objects.get(k);
     out.list.rows.push({i,key:k,obj:row,flags:row?u(row+0x18):null,
      rect:row?[0x88,0x8c,0x90,0x94].map(o=>gm.add(row+o).readFloat()):null});}
   }
  }else if(safe(vt+0x60)===0x83a2020){
   out.binding={press:q(obj+0x60),logical:q(obj+0x68),predicate:q(obj+0x70),
    action:gm.add(obj+0x78).readS32(),lastKey:u(obj+0x7c)};
  }
  return out;
 }
 const roots=q(manager+0x10),data=q(roots),count=u(roots+8);
 if(count>1024)throw new Error('invalid subscriber count');
 const out={manager,keys:[0x20,0x28,0x30,0x38,0x40,0x48,0x50].map(o=>[o,key(manager+o)]),roots:[]};
 for(let i=0;i<count;i++){
  const obj=q(data+i*8),route=info(obj);route.i=i;route.ancestors=[];
  let parent=route.parent;
  for(let k=0;k<32&&parent!=='18446744073709551615';k++){
   const p=objects.get(parent);if(!p){route.unresolvedParent=parent;break;}
   const a=info(p);route.ancestors.push(a);parent=a.parent;
  }
  out.roots.push(route);
 }
 return out;
}};
"""


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid",type=int,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    build=assert_installed()
    session=frida.attach(args.pid)
    try:
        script=session.create_script(JS);script.load();data=script.exports_sync.read()
    finally:
        session.detach()
    names=dict(names_for("."))
    def name_object(o):
        o["name"]=names.get(o["key"])
        for a in o.get("ancestors",[]):name_object(a)
    for r in data["roots"]:name_object(r)
    data.update(build=build,pid=args.pid)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,indent=2),"utf-8")
    for r in data["roots"]:
        print(r["i"],r["obj"],r["name"] or r["key"],hex(r["vt"]),
              r.get("callbacks",r.get("binding")),r.get("list",{}).get("selected"))


if __name__=="__main__":
    main()
