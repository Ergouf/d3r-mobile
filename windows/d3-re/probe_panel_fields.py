import json, frida
from pathlib import Path
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function s(a){return gm.add(a).readS32();}
function f(a){return gm.add(a).readFloat();}
function rect(o){try{return [0,1,2,3].map(i=>Math.round(f(o+0x88+i*4)));}catch(e){return null;}}
function info(g){
  if(!g) return null;
  let vt=0; try{vt=q(g);}catch(e){return {g, err:String(e)};}
  return {g, vt, w18:u(g+0x18), id:s(g+0xc), n68:u(g+0x68), p60:q(g+0x60),
          p30:q(g+0x30), p38:q(g+0x38), rect:rect(g), w48:u(g+0x48), w4c:u(g+0x4c)};
}
rpc.exports={read(){
  const panel=0x15ee03b80;
  const fields={};
  for(const off of [0xc,0x18,0x138,0x140,0x148,0x150,0x154,0x208,0xcd8,0xd60,0xde8,0xe70,0xee8,0xf60,0xfd8,0x1100,0x1198,0x1388,0x138c,0x1390,0x1394]){
    let rec={off};
    try{
      if(off<=0x154 || off>=0x1388) rec.u=u(panel+off), rec.q=q(panel+off);
      else rec.q=q(panel+off), rec.u=u(panel+off);
    }catch(e){rec.err=String(e);}
    fields[off]=rec;
  }
  const ptrs=[0x138,0x140,0xcd8,0xd60,0xde8,0xe70,0xee8,0xf60,0xfd8,0x1100,0x1198].map(off=>{
    const p=q(panel+off);
    return {off, p, info:p?info(p):null, slot:p?info(q(p)):null};
  });
  // focus slot: world manager +0x50
  const global=q(0x914f840), world=q(global+0x10), manager=q(world+0xb80);
  const focus=q(manager+0x50);
  return {panel:info(panel), fields, ptrs, manager, focus, focusInfo:focus?info(focus):null,
          ringHi:q(0x15d47f700+0x538)};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
Path(r"out/windows/kbm/session/round82-panel.json").write_text(json.dumps(data), encoding="utf-8")
print("panel", {k:(hex(v) if isinstance(v,int) else v) for k,v in data["panel"].items()})
print("manager", hex(data["manager"]), "focus", hex(data["focus"]), "ringHi", hex(data["ringHi"]))
print("focusInfo", data["focusInfo"])
for p in data["ptrs"]:
    print(f"+{p['off']:#x} -> {p['p']:#x} info={p['info']}")
print("--- small fields")
for off, rec in data["fields"].items():
    if rec.get("u", 0) < 64 or off in ("1388","1390","1394","154"):
        print(off, rec)
