"""Read-only: where the selected equipment item pointer is stored."""
from __future__ import annotations
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
]
SLOTS = ["head","shoulder","neck","torso","hands","bracers","waist","legs","feet",
         "fingerleft","fingerright","armleft","armright","bag"]
for s in SLOTS:
    NAMES.append("root.normallayer.consoleinventoryring_main.layoutroot.inventoryring.button_" + s)

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function keyOf(a){return gm.add(a).readU64().toString();}
function rect(o){return [0,1,2,3].map(i=>Math.round(f(o+0x88+i*4)));}
rpc.exports={read(keys){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  const byKey=new Map(), kids=new Map();
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const k=keyOf(node+8), obj=q(node+0x10);
    if(!obj) continue;
    byKey.set(k, obj);
    const pk=keyOf(obj+0x38);
    if(!kids.has(pk)) kids.set(pk, []);
    kids.get(pk).push(obj);
  }
  function visible(obj){
    let o=obj;
    for(let i=0;o && i<64;i++){
      let flags=0, parent=0;
      try{ flags=u(o+0x18); parent=q(o+0x38);}catch(e){return false;}
      if((flags & 4)===0) return false;
      if(parent===0xffffffffffffffff) return true;
      o=byKey.get(parent.toString())||0;
    }
    return false;
  }
  const found={};
  keys.forEach((k,i)=>{ found[i]=byKey.get(k)||0; });
  const ring=found[1], equipped=found[2], page=found[0];
  const items=[];
  for(let i=3;i<keys.length;i++){
    const btn=found[i];
    if(!btn) { items.push({i, missing:true}); continue; }
    const data=q(btn+0x60), count=u(btn+0x68);
    let comp=0, icon=0, item=0;
    if(data && count<=8){
      for(let c=0;c<count;c++){
        const child=q(data + c*24 + 8);
        if(!child) continue;
        const vt=q(child);
        if(vt===0x90aab58){ comp=child; item=q(child+0x78); }
      }
    }
    // visible icon among registry children with matching rect
    const br=rect(btn);
    const ck=kids.get(keyOf(btn+0x30))||[];
    const icons=[];
    for(const o of ck){
      let vt=0, m60=0;
      try{ vt=q(o); m60=q(vt+0x60);}catch(e){continue;}
      if(m60!==0x8392410) continue;
      const r=rect(o);
      icons.push({o, r, hi:u(o+0x464), vis:visible(o), flags:u(o+0x18)});
    }
    items.push({slot:i-3, btn, rect:br, vis:visible(btn), flags:u(btn+0x18), comp, item, icons});
  }
  const wanted=new Set(items.map(x=>x.item).filter(Boolean));
  function scan(obj, depth, seen, hits){
    if(!obj || depth>8 || seen.has(obj)) return;
    seen.add(obj);
    let bytes;
    try{ bytes=gm.add(obj).readByteArray(0x600); }catch(e){ return; }
    const dv=new DataView(bytes);
    for(let off=0; off<=0x600-8; off+=8){
      const lo=dv.getUint32(off, true);
      const hi=dv.getUint32(off+4, true);
      const p=hi*0x100000000 + lo;
      if(wanted.has(p)) hits.push({obj, off, p, depth, vt:q(obj)});
    }
    for(const c of (kids.get(keyOf(obj+0x30))||[])) scan(c, depth+1, seen, hits);
  }
  const hits=[];
  if(equipped) scan(equipped, 0, new Set(), hits);
  const ringHits=[];
  if(ring){
    const dv=new DataView(gm.add(ring).readByteArray(0x800));
    for(let off=0; off<=0x800-8; off+=8){
      const p=dv.getUint32(off+4,true)*0x100000000 + dv.getUint32(off,true);
      if(wanted.has(p)) ringHits.push({off, p});
    }
  }
  function panel(addr){
    const slot=q(addr), obj=slot?q(slot):0;
    if(!obj) return {addr, slot, obj};
    const vt=q(obj);
    const slots=[];
    for(let i=0;i<20;i++) slots.push(q(vt+i*8));
    return {addr, obj, vt, w18:u(obj+0x18), id:u(obj+0xc), slots};
  }
  let itemHead=null;
  const first=items.find(x=>x.item);
  if(first){
    const p=first.item;
    itemHead={p, vt:q(p), w0:q(p), w8:q(p+8), w10:q(p+0x10), w18:q(p+0x18)};
  }
  const hi=ring?q(ring+0x538):0;
  return {registry:byKey.size, page, ring, equipped, pageVis: page?visible(page):false,
          hi, hiVis: hi?visible(hi):false, hiRect: hi?rect(hi):null, hiFlag: hi?u(hi+0x464):null,
          items, hits, ringHits, panels:[panel(0x9157F58), panel(0x9159950)], itemHead};
}};
"""

def main():
    build=assert_installed()
    keys=[str(fnv1a64(n.lower().encode())) for n in NAMES]
    s=frida.get_local_device().attach(6032)
    try:
        j=s.create_script(JS); j.load(); data=j.exports_sync.read(keys)
    finally:
        s.detach()
    data["build"]=build
    Path(r"out/windows/kbm/session/round81-bind.json").write_text(json.dumps(data), encoding="utf-8")
    print("page", hex(data["page"]), "vis", data["pageVis"], "ring", hex(data["ring"]), "eq", hex(data["equipped"]))
    print("hi", hex(data["hi"] or 0), data["hiRect"], "flag", data["hiFlag"], "hivis", data["hiVis"])
    print("itemHead", {k:(hex(v) if isinstance(v,int) else v) for k,v in (data["itemHead"] or {}).items()})
    print("---slots")
    for it in data["items"]:
        if it.get("missing"):
            print("missing", it); continue
        print(f"{SLOTS[it['slot']]:12} btn={it['btn']:#x} vis={it['vis']} item={it['item']:#x} icons={[(hex(i['o']), i['r'], i['hi'], i['vis']) for i in it['icons']]}")
    print("---equipped hits", len(data["hits"]))
    for h in data["hits"][:40]:
        print(f"  obj={h['obj']:#x} +{h['off']:#x} item={h['p']:#x} depth={h['depth']} vt={h['vt']:#x}")
    print("---ring hits", data["ringHits"])
    for p in data["panels"]:
        print("panel", hex(p.get("obj") or 0), "w18", p.get("w18"), "id", p.get("id"))
        if p.get("slots"):
            print("  vt", " ".join(hex(x) for x in p["slots"][:12]))

if __name__=="__main__":
    main()
