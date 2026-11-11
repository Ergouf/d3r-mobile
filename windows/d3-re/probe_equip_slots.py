"""Read inventory panel singletons and equipment-slot highlight. No writes."""
from __future__ import annotations
import json
from pathlib import Path
import frida
from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function key(a){return gm.add(a).readU64().toString();}
function rect(a){return [0x88,0x8c,0x90,0x94].map(o=>gm.add(a+o).readFloat());}
const GLOBALS = [
  ['0x83757f0', 0x9157F58],
  ['0x842a8c0', 0x9159950],
  ['0x81ee480', 0x9153F38],
  ['0x837dde0', 0x9158028],
  ['0x8427580', 0x9159948],
  ['0x8419000', 0x91598B0],
  ['0x81df930', 0x9153E68],
  ['0x81bc220', 0x91537C0],
  ['0x81802c0', 0x9152818],
  ['0x81a5e90', 0x9153278],
  ['0x8222b30-slot', 0x91545F0],
];
rpc.exports = { read() {
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10), registry=new Map();
  if(mask>262143) throw new Error('bad registry');
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node))
    registry.set(key(node+8), q(node+0x10));
  function visible(obj){
    const seen=new Set();
    for(let i=0; obj&&i<64; i++){
      if(seen.has(obj)||!(u(obj+0x18)&4)) return false;
      seen.add(obj);
      const pk=key(obj+0x38);
      if(pk==='18446744073709551615') return true;
      obj=registry.get(pk);
    }
    return false;
  }
  const panels = GLOBALS.map(([name, addr]) => {
    const slot = q(addr), obj = slot ? q(slot) : 0;
    const item = {name, addr, slot, obj, active:0};
    if(!obj) return item;
    try {
      item.word18 = u(obj+0x18);
      item.active = item.word18 ? 1 : 0;
      item.vt = q(obj);
      item.handler = q(item.vt+0x48);
      const words=[];
      for(let off=0; off<0x80; off+=4) words.push({off, v:u(obj+off)});
      item.words = words;
    } catch(e) { item.error=String(e); }
    return item;
  });
  const slots=[];
  for(const obj of registry.values()){
    if(q(obj)!==0x90abb48 || !visible(obj)) continue;
    const r=rect(obj); const w=r[2]-r[0], h=r[3]-r[1];
    if(w<50||w>70||h<50||h>70) continue;
    let parent=registry.get(key(obj+0x38))||0;
    let paper=parent;
    for(let i=0; paper&&i<6; i++){
      const pr=rect(paper);
      if((pr[2]-pr[0])>200 && (pr[3]-pr[1])>200) break;
      paper=registry.get(key(paper+0x38))||0;
    }
    slots.push({obj, rect:r, flags:u(obj+0x18), hi:u(obj+0x464), idA:u(obj+0x45c), idB:u(obj+0x460),
      b4b0:u(obj+0x4b0), b4ac:u(obj+0x4ac), parent, paper,
      paperHi: paper?q(paper+0x538):0, paperHi2: paper?q(paper+0x540):0});
  }
  const texts=[];
  for(const obj of registry.values()){
    if(!visible(obj)) continue;
    const vt=q(obj);
    if(vt!==0x90ae520 && vt!==0x90abb48) continue;
    const ptr=q(obj+0x398), cap=u(obj+0x3a0);
    if(!ptr||cap<2||cap>4096) continue;
    let text=null;
    try { text=gm.add(ptr).readUtf8String(Math.min(cap,180)); } catch(e) { text='ERR'; }
    if(text && text.length>1) texts.push({obj, rect:rect(obj), text});
  }
  return {panels, slots, texts};
}};
"""

def main():
    build=assert_installed()
    s=frida.get_local_device().attach(6032)
    try:
        j=s.create_script(JS); j.load(); data=j.exports_sync.read()
    finally:
        s.detach()
    data["build"]=build
    out=Path(r"out/windows/kbm/session/round79-panels.json")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in data["panels"]:
        if p.get("obj"):
            print(f"panel {p['name']} obj={p['obj']:#x} active={p.get('active')} word18={p.get('word18')} vt={p.get('vt',0):#x} handler={p.get('handler',0):#x}")
    print("---slots", len(data["slots"]))
    for sl in sorted(data["slots"], key=lambda s:(s["rect"][1], s["rect"][0])):
        print(f"  {sl['obj']:#x} rect={[round(x) for x in sl['rect']]} hi={sl['hi']} paper={sl['paper']:#x} paperHi={sl['paperHi']:#x}")
    print("---texts", len(data["texts"]))
    for t in data["texts"]:
        if t["rect"][1] > 400 or "A " in t["text"] or len(t["text"])>8:
            print(f"  {t['obj']:#x} {[round(x) for x in t['rect']]} {t['text'][:80]!r}")

if __name__=="__main__":
    main()
