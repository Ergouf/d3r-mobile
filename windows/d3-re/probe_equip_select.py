"""Read-only snapshot of inventory slot highlight and equipped-item text."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import frida
from version import assert_installed, js_consts

MASK64 = (1 << 64) - 1

def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in data:
        h = ((h ^ c) * 0x100000001B3) & MASK64
    return h

NAMES = [
    "root.normallayer.consoleinventoryring_main",
    "root.normallayer.consoleinventoryring_main.layoutroot.inventoryring",
    "root.normallayer.consoleinventoryring_main.layoutroot.equippeditem",
    "root.normallayer.consoleinventoryring_main.layoutroot.inventoryring.ringglow.cursor",
]
SLOTS = ["head","shoulder","neck","torso","hands","bracers","waist","legs","feet",
         "fingerleft","fingerright","armleft","armright","bag"]
for s in SLOTS:
    NAMES.append("root.normallayer.consoleinventoryring_main.layoutroot.inventoryring.button_" + s)

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function key(a){return gm.add(a).readU64().toString();}
function rect(a){return [0x88,0x8c,0x90,0x94].map(o=>f(a+o));}
function textAt(obj){
  try{
    const ptr=q(obj+0x398), cap=u(obj+0x3a0);
    if(!ptr || cap<2 || cap>4096) return null;
    const s=gm.add(ptr).readUtf8String(Math.min(cap, 160));
    return s && s.length ? s : null;
  }catch(e){return null;}
}
rpc.exports = { read(keys, names) {
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  if(mask>262143) throw new Error('bad registry');
  const byKey=new Map();
  const kids=new Map();
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const k=key(node+8), obj=q(node+0x10);
    if(!obj) continue;
    byKey.set(k, obj);
    const pk=key(obj+0x38);
    if(!kids.has(pk)) kids.set(pk, []);
    kids.get(pk).push(obj);
  }
  function named(i){
    const k=keys[i];
    const obj=byKey.get(k)||0;
    if(!obj) return {name:names[i], found:false};
    return {name:names[i], found:true, obj, vt:q(obj), flags:u(obj+0x18), rect:rect(obj),
            b4:u(obj+0xb4), parent:key(obj+0x38)};
  }
  function kidsOf(obj){
    const out=[];
    const data=q(obj+0x60), count=u(obj+0x68);
    if(!data || count>64) return out;
    for(let i=0;i<count;i++){
      let child=0;
      try{ child=q(data + i*24 + 8); }catch(e){ continue; }
      if(!child) continue;
      let item={i, child, vt:0, flags:0, rect:null, hi:null, text:null};
      try{
        item.vt=q(child); item.flags=u(child+0x18); item.rect=rect(child);
        item.hi=u(child+0x464); item.idA=u(child+0x45c); item.idB=u(child+0x460);
        item.b4=u(child+0xb4); item.text=textAt(child);
      }catch(e){ item.error=String(e); }
      out.push(item);
    }
    return out;
  }
  function deepText(obj, depth, seen, acc){
    if(!obj || depth>6 || seen.has(obj)) return;
    seen.add(obj);
    const t=textAt(obj);
    if(t){
      try{ acc.push({obj, vt:q(obj), rect:rect(obj), text:t}); }
      catch(e){ acc.push({obj, text:t}); }
    }
    for(const c of (kids.get(key(obj+0x30))||[])) deepText(c, depth+1, seen, acc);
  }
  const found=keys.map((_,i)=>named(i));
  const ring=found.find(x=>x.name.endsWith('.inventoryring') && x.found);
  const equipped=found.find(x=>x.name.endsWith('.equippeditem') && x.found);
  const buttons=found.filter(x=>x.found && x.name.includes('.button_')).map(b=>{
    b.children=kidsOf(b.obj);
    return b;
  });
  const texts=[];
  if(equipped) deepText(equipped.obj, 0, new Set(), texts);
  const ringKids = ring ? kidsOf(ring.obj) : [];
  let ringFields=null;
  if(ring){
    const hi=q(ring.obj+0x538), hi2=q(ring.obj+0x540);
    ringFields={hi, hi2, hiFlag: hi?u(hi+0x464):null, hiRect: hi?rect(hi):null,
                f200:f(ring.obj+0x200), w48:q(ring.obj+0x48)};
  }
  function panel(addr){
    const slot=q(addr), obj=slot?q(slot):0;
    if(!obj) return {addr, slot, obj};
    let a=null,b=null;
    try{ a=q(obj+0x138); b=q(obj+0x140); }catch(e){}
    function peek(p){
      if(!p) return null;
      try{ return {p, vt:q(p), w18:u(p+0x18), f200:f(p+0x200), n:u(p+0x68)}; }
      catch(e){ return {p, error:String(e)}; }
    }
    return {addr, slot, obj, vt:q(obj), w18:u(obj+0x18), id:u(obj+0xc), a:peek(a), b:peek(b)};
  }
  return {registry:byKey.size, found, buttons, ringKids, ringFields, equippedTexts:texts,
          panels:[panel(0x9157F58), panel(0x9159950)]};
}};
"""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=6032)
    ap.add_argument("--out", type=Path, default=Path(r"out/windows/kbm/session/round80-equip-snapshot.json"))
    args=ap.parse_args()
    build=assert_installed()
    keys=[str(fnv1a64(n.lower().encode())) for n in NAMES]
    s=frida.get_local_device().attach(args.pid)
    try:
        j=s.create_script(JS); j.load(); data=j.exports_sync.read(keys, NAMES)
    finally:
        s.detach()
    data["build"]=build
    out=args.out
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("registry", data["registry"])
    rf=data.get("ringFields")
    print("ring", rf)
    print("---buttons")
    for b in data["buttons"]:
        kids=b.get("children") or []
        brief=[]
        for c in kids:
            r=c.get("rect") or [0,0,0,0]
            brief.append(f"vt={c.get('vt'):#x} hi={c.get('hi')} rect={[round(x) for x in r]} id={c.get('idA')}/{c.get('idB')}")
        rb=[round(x) for x in b["rect"]]
        print(f"{b['name'].split('.')[-1]} obj={b['obj']:#x} rect={rb} b4={b['b4']} kids={brief}")
    print("---equipped texts", len(data["equippedTexts"]))
    for t in data["equippedTexts"]:
        r=t.get("rect")
        rr=[round(x) for x in r] if r else None
        print(f"  {t['obj']:#x} {rr} {t['text'][:100]!r}")
    print("---panels")
    for p in data["panels"]:
        print(p)

if __name__=="__main__":
    main()
