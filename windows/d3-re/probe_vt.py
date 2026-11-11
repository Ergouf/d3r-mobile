import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
rpc.exports={read(){
  const vts=[0x90af208,0x90abb48,0x90aab58,0x90aaee0];
  const out={};
  for(const vt of vts){
    const slots=[];
    for(let i=0;i<0x30;i++) slots.push(q(vt+i*8));
    out[vt.toString(16)]=slots;
  }
  // button +0xb4 and callback table
  const btn=0x15d47f9c0;
  return {out, b4: gm.add(btn+0xb4).readS32(), cb:q(btn+0x118), e0:q(0x90af208+0xe0), s68:q(0x90af208+0x68)};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
for name, slots in data["out"].items():
    print("vt", name)
    for i,sl in enumerate(slots):
        if i in (0x60//8,0x68//8,0x78//8,0xb0//8,0xe0//8,0x108//8,0x138//8) or True:
            if i%4==0:
                pass
        print(f"  +{i*8:#04x} {sl:#x}")
print("btn b4", data["b4"], "cb", hex(data["cb"]), "e0", hex(data["e0"]), "68", hex(data["s68"]))
