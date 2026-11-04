import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
function key(a){return gm.add(a).readU64().toString();}
rpc.exports={read(){
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80), map=q(manager);
  const mask=u(map), buckets=q(map+0x10);
  const kids=new Map();
  for(let b=0;b<=mask;b++) for(let node=q(buckets+b*8),g=0; node&&g++<1024; node=q(node)){
    const obj=q(node+0x10);
    if(!obj) continue;
    const pk=key(obj+0x38);
    if(!kids.has(pk)) kids.set(pk,[]);
    kids.get(pk).push(obj);
  }
  const page=0x15d7b08a0;
  const icons=[]; const lists=[];
  const seen=new Set();
  const stack=[page];
  while(stack.length){
    const o=stack.pop();
    if(!o||seen.has(o)) continue; seen.add(o);
    let vt=0; try{vt=q(o);}catch(e){continue;}
    let m60=0,mE0=0; try{m60=q(vt+0x60); mE0=q(vt+0xe0);}catch(e){}
    if(m60===0x8392410){
      const r=[0x88,0x8c,0x90,0x94].map(x=>f(o+x));
      icons.push({o, r, hi:u(o+0x464), a:u(o+0x45c), b:u(o+0x460), c:u(o+0x4b0), d:u(o+0x4ac), h:q(o+0x4c0)});
    }
    if(mE0===0x838C6C0){
      lists.push({o, r:[0x88,0x8c,0x90,0x94].map(x=>Math.round(f(o+x))), n:u(o+0x218), sel:u(o+0x1e0)});
    }
    for(const c of (kids.get(key(o+0x30))||[])) stack.push(c);
  }
  return {seen:seen.size, icons, lists};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
print("seen", data["seen"], "icons", len(data["icons"]), "lists", len(data["lists"]))
for ic in sorted(data["icons"], key=lambda s:(round(s["r"][1]), round(s["r"][0]))):
    r=[round(x) for x in ic["r"]]
    print(f"{ic['o']:#x} {r} hi={ic['hi']} 45c={ic['a']} 460={ic['b']} 4b0={ic['c']} 4ac={ic['d']} h={ic['h']:#x}")
print("---lists")
for L in data["lists"]:
    print(hex(L["o"]), L["r"], "rows", L["n"], "sel", L["sel"])
