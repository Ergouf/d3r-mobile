import json, frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function keyOf(a){return gm.add(a).readU64().toString();}
function rect(o){try{return [0,1,2,3].map(i=>Math.round(f(o+0x88+i*4)));}catch(e){return null;}}
function info(o){
  if(!o) return null;
  const vt=q(o);
  return {o, vt, flags:u(o+0x18), rect:rect(o), key:keyOf(o+0x30), parent:keyOf(o+0x38),
          onEvent:q(vt+0x60), hit:q(vt+0x78), n:u(o+0x68), hi:u(o+0x464), b1b0:u(o+0x1b0)};
}
rpc.exports={read(){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  const kids=new Map();
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const obj=q(node+0x10); if(!obj) continue;
    const pk=keyOf(obj+0x38);
    if(!kids.has(pk)) kids.set(pk,[]);
    kids.get(pk).push(obj);
  }
  function walk(o, depth, acc){
    if(!o || depth>5 || acc.length>80) return;
    const inf=info(o); inf.depth=depth; acc.push(inf);
    const data=q(o+0x60), count=u(o+0x68);
    const seen=new Set();
    if(data && count>0 && count<=32){
      for(let i=0;i<count;i++){
        let c=0; try{c=q(data+i*24+8);}catch(e){continue;}
        if(c){seen.add(c); walk(c, depth+1, acc);}
      }
    }
    for(const c of (kids.get(keyOf(o+0x30))||[])) if(!seen.has(c)) walk(c, depth+1, acc);
  }
  const acc=[];
  walk(0x159a2fda0, 0, acc);
  // also direct registry children of highlight parent
  const parentKids=(kids.get(keyOf(0x15d47fbc0+0x30))||[]).map(info);
  return {center:acc, parentKids, parent:info(0x15d47fbc0)};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
print("parent", data["parent"])
print("parent kids", len(data["parentKids"]))
for c in data["parentKids"]:
    print(" ", hex(c["o"]), hex(c["vt"]), c["rect"], "ev", hex(c["onEvent"]), "hi", c["hi"], "fl", hex(c["flags"]))
print("center walk", len(data["center"]))
for c in data["center"]:
    if c["depth"]>3: continue
    print(" "*c["depth"], hex(c["o"]), "vt", hex(c["vt"]), c["rect"], "ev", hex(c["onEvent"]), "n", c["n"], "hi", c["hi"], "fl", hex(c["flags"]))
