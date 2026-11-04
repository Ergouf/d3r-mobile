"""Read-only equipped-item tree and visible UI strings."""
from __future__ import annotations
import json
from pathlib import Path
import frida
from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
rpc.exports={read(){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  const texts=[];
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const obj=q(node+0x10);
    if(!obj) continue;
    let ptr,cap;
    try{ ptr=q(obj+0x398); cap=u(obj+0x3a0);}catch(e){continue;}
    if(!ptr||cap<2||cap>512) continue;
    let s=null;
    try{ s=gm.add(ptr).readUtf8String(Math.min(cap,140)); }catch(e){continue;}
    if(!s||s.length<2) continue;
    let vt=0,r=null;
    try{ vt=q(obj); r=[0x88,0x8c,0x90,0x94].map(o=>f(obj+o)); }catch(e){}
    texts.push({obj,vt,rect:r,text:s});
  }
  function walk(obj, depth, acc, seen){
    if(!obj||depth>6||seen.has(obj)||acc.length>120) return;
    seen.add(obj);
    const item={obj,depth};
    try{
      item.vt=q(obj); item.flags=u(obj+0x18);
      item.rect=[0x88,0x8c,0x90,0x94].map(o=>f(obj+o));
      const ptr=q(obj+0x398), cap=u(obj+0x3a0);
      if(ptr&&cap>=2&&cap<1024){ try{ item.text=gm.add(ptr).readUtf8String(Math.min(cap,100)); }catch(e){} }
    }catch(e){ item.error=String(e); }
    acc.push(item);
    let data=0,count=0;
    try{ data=q(obj+0x60); count=u(obj+0x68);}catch(e){return;}
    if(!data||count>48) return;
    for(let i=0;i<count;i++){
      let c=0; try{c=q(data+i*24+8);}catch(e){continue;}
      walk(c, depth+1, acc, seen);
    }
  }
  const tree=[];
  walk(0x15d7b2e00,0,tree,new Set());
  const icons=[];
  walk(0x15d47f700,0,icons,new Set());
  return {texts, tree, icons};
}};
"""

def finite(r):
    return r and all(isinstance(x,(int,float)) for x in r)

def main():
    build=assert_installed()
    s=frida.get_local_device().attach(6032)
    try:
        j=s.create_script(JS); j.load(); data=j.exports_sync.read()
    finally:
        s.detach()
    data["build"]=build
    Path(r"out/windows/kbm/session/round80-texts.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("texts", len(data["texts"]), "tree", len(data["tree"]), "icons", len(data["icons"]))
    print("--- equipped tree")
    for t in data["tree"]:
        r=t.get("rect")
        rr=[round(x) for x in r] if finite(r) else None
        tx=(t.get("text") or "")[:70]
        print("  "*t["depth"]+f"{t['obj']:#x} vt={t.get('vt',0):#x} {rr} {tx!r}")
    print("--- interesting texts")
    for t in data["texts"]:
        tx=t["text"]
        r=t.get("rect")
        if not finite(r):
            continue
        if r[1] < 300 and len(tx) < 8:
            continue
        print(f"{t['obj']:#x} vt={t['vt']:#x} {[round(x) for x in r]} {tx[:80]!r}")

if __name__=="__main__":
    main()
