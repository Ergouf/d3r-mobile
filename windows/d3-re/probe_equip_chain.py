"""Parent chain and item-blob shape for the highlighted equipment icon."""
import json
from pathlib import Path
import frida
from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function keyOf(a){return gm.add(a).readU64().toString();}
function rect(o){
  try{return [0,1,2,3].map(i=>Math.round(f(o+0x88+i*4)));}catch(e){return null;}
}
rpc.exports={read(){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  const byKey=new Map();
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const obj=q(node+0x10); if(!obj) continue;
    byKey.set(keyOf(node+8), obj);
  }
  function chain(obj){
    const out=[]; let o=obj;
    for(let i=0;o && i<12;i++){
      const flags=u(o+0x18), parent=q(o+0x38), vt=q(o);
      out.push({o, vt, flags, parent, rect:rect(o), visbit:(flags&4)!==0});
      if(parent===0xffffffffffffffff) break;
      o=byKey.get(parent.toString())||0;
      if(!o){ out.push({missingParent:parent.toString()}); break; }
    }
    return out;
  }
  function blob(p){
    const bytes=Array.from(new Uint8Array(gm.add(p).readByteArray(96)));
    const words=[];
    for(let i=0;i<96;i+=8){
      let v=0; try{v=q(p+i);}catch(e){v=0;}
      words.push(v);
    }
    return {bytes, words};
  }
  // find visible objects whose rect is inside paper doll and about 59px
  const dolls=[];
  for(const obj of byKey.values()){
    const r=rect(obj); if(!r) continue;
    const w=r[2]-r[0], h=r[3]-r[1];
    if(w<50||w>70||h<50||h>70) continue;
    if(r[0]<0||r[0]>380||r[1]<50||r[1]>430) continue;
    const flags=u(obj+0x18);
    if((flags&4)===0) continue;
    dolls.push({o:obj, vt:q(obj), flags, r, hi:u(obj+0x464)});
  }
  return {
    hiChain: chain(0x158b7c920),
    btnChain: chain(0x15d47f9c0),
    pageChain: chain(0x15d7b08a0),
    arm: blob(0x15aecf6f0),
    head: blob(0x15aed0070),
    dolls
  };
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
Path(r"out/windows/kbm/session/round81-chain.json").write_text(json.dumps(data), encoding="utf-8")

def show(name, chain):
    print("==", name)
    for c in chain:
        if "missingParent" in c:
            print("  missing", c["missingParent"]); continue
        print(f"  {c['o']:#x} vt={c['vt']:#x} flags={c['flags']:#x} bit4={c['visbit']} rect={c['rect']}")

show("hi", data["hiChain"])
show("btn", data["btnChain"])
show("page", data["pageChain"])
print("visible doll-sized", len(data["dolls"]))
for d in data["dolls"][:30]:
    print(f"  {d['o']:#x} vt={d['vt']:#x} flags={d['flags']:#x} hi={d['hi']} {d['r']}")
print("arm words", [hex(w) for w in data["arm"]["words"][:8]])
print("head words", [hex(w) for w in data["head"]["words"][:8]])
print("arm bytes", bytes(data["arm"]["bytes"][:64]).hex())
