import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function f(a){return gm.add(a).readFloat();}
rpc.exports={read(){
  const panel=q(q(0x9159950));
  const offs=[0x138,0x140,0x148,0x200,0x208,0x210,0x218,0x220,0xae8,0xaf0,0xb00,0xb08,0x1620];
  const fields={};
  for (const off of offs) fields[off]=q(panel+off);
  const ctrl=fields[0x208];
  let ctrlInfo=null;
  if (ctrl) {
    ctrlInfo={vt:q(ctrl), w18:u(ctrl+0x18), f200:f(ctrl+0x200), n68:u(ctrl+0x68)};
  }
  return {panel, fields, ctrlInfo};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
print("panel", hex(data["panel"]))
for off,v in data["fields"].items():
    print(f"+{int(off):#x} {v:#x}")
print("ctrl", data["ctrlInfo"])
