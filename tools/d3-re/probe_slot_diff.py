import json, frida
from pathlib import Path
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function keyOf(a){return gm.add(a).readU64().toString();}
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
  function iconUnder(btn){
    const data=q(btn+0x60), count=u(btn+0x68);
    const icons=[];
    for(let i=0;i<count;i++){
      const child=q(data+i*24+8);
      if(!child) continue;
      for(const o of (kids.get(keyOf(child+0x30))||[])){
        try{ if(q(q(o)+0x60)===0x8392410) icons.push(o); }catch(e){}
      }
    }
    return icons;
  }
  function words(o,n){const a=[]; for(let i=0;i<n;i++) a.push(q(o+i*8)); return a;}
  const armBtn=0x15d47f9c0, headBtn=0x159a21ac0;
  const armIcons=iconUnder(armBtn), headIcons=iconUnder(headBtn);
  return {
    armIcons, headIcons,
    armBtn: words(armBtn, 0x80),
    headBtn: words(headBtn, 0x80),
    armIcon: armIcons[0]?words(armIcons[0], 0xA0):null,
    headIcon: headIcons[0]?words(headIcons[0], 0xA0):null
  };
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
Path(r"out/windows/kbm/session/round81-diff.json").write_text(json.dumps(data), encoding="utf-8")
print("arm icons", [hex(x) for x in data["armIcons"]])
print("head icons", [hex(x) for x in data["headIcons"]])

def diff(name, a, b):
    print("==", name)
    if not a or not b:
        print(" missing"); return
    for i,(x,y) in enumerate(zip(a,b)):
        if x==y: continue
        # skip huge identical-looking floats packed; show all diffs but mark small
        mark=""
        if x<0x100000 and y<0x100000: mark=" SMALL"
        print(f"  +{i*8:#05x} {x:#x} {y:#x}{mark}")

diff("btn", data["armBtn"], data["headBtn"])
diff("icon", data["armIcon"], data["headIcon"])
