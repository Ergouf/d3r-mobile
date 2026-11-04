import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
rpc.exports={read(){
  const vts=[0x90aaee0, 0x90b0060];
  return vts.map(vt=>{
    const e=[];
    for(let i=0;i<16;i++) e.push(q(vt+i*8));
    return {vt, e};
  });
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
for item in data:
    print(hex(item["vt"]))
    for i,e in enumerate(item["e"]):
        print(f"  +{i*8:#x} {e:#x}")
