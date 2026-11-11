import json
from pathlib import Path
import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function keyOf(a){return gm.add(a).readU64().toString();}
function rect(o){try{return [0,1,2,3].map(i=>Math.round(f(o+0x88+i*4)));}catch(e){return null;}}
rpc.exports={read(){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  const byKey=new Map(); const kids=new Map();
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const k=keyOf(node+8), obj=q(node+0x10); if(!obj) continue;
    byKey.set(k, obj);
    const pk=keyOf(obj+0x38);
    if(!kids.has(pk)) kids.set(pk,[]);
    kids.get(pk).push(obj);
  }
  function info(o){
    if(!o) return null;
    let vt=0,m60=0,m78=0,mE0=0;
    try{vt=q(o); m60=q(vt+0x60); m78=q(vt+0x78); mE0=q(vt+0xe0);}catch(e){}
    return {o, vt, flags:u(o+0x18), rect:rect(o), key:keyOf(o+0x30), parent:keyOf(o+0x38),
            m60, m78, mE0, hi:u(o+0x464), n60:u(o+0x68)};
  }
  function arrKids(o){
    const data=q(o+0x60), count=u(o+0x68);
    const out=[];
    if(!data || count>64) return {count, out};
    for(let i=0;i<count;i++){
      let child=0; try{child=q(data+i*24+8);}catch(e){continue;}
      out.push(info(child));
    }
    return {count, out};
  }
  const ring=0x15d47f700, page=0x15d7b08a0;
  const regKids=(kids.get(keyOf(ring+0x30))||[]).map(info);
  const pageKids=(kids.get(keyOf(page+0x30))||[]).slice(0,40).map(info);
  // who points at the highlight icon via registry parent
  const hi=0x158b7c920;
  const hiParentKey=keyOf(hi+0x38);
  const hiParent=byKey.get(hiParentKey)||0;
  return {
    ring:info(ring), ringArr:arrKids(ring), regKids,
    page:info(page), pageArr:arrKids(page), pageKids,
    hi:info(hi), hiParent, hiParentKey
  };
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
Path(r"out/windows/kbm/session/round81-tree.json").write_text(json.dumps(data), encoding="utf-8")

def brief(x):
    if not x: return None
    return f"{x['o']:#x} vt={x['vt']:#x} fl={x['flags']:#x} r={x['rect']} m60={x['m60']:#x} n60={x['n60']} hi={x['hi']}"
print("RING", brief(data["ring"]))
print(" ring arr", data["ringArr"]["count"])
for c in data["ringArr"]["out"]:
    print("  ", brief(c))
print(" ring registry kids", len(data["regKids"]))
for c in data["regKids"][:25]:
    print("  ", brief(c))
print("PAGE", brief(data["page"]))
print(" page arr", data["pageArr"]["count"])
for c in data["pageArr"]["out"][:20]:
    print("  ", brief(c))
print(" page registry kids", len(data["pageKids"]))
for c in data["pageKids"][:15]:
    print("  ", brief(c))
print("HI", brief(data["hi"]), "parentKey", data["hiParentKey"], "parentObj", hex(data["hiParent"] or 0))
