import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
rpc.exports={read(){
  const vt=0x90a32c0; const e=[];
  for(let i=0;i<24;i++) e.push(q(vt+i*8));
  return e;
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); e=j.exports_sync.read()
finally:
    s.detach()
for i,v in enumerate(e):
    print(f"+{i*8:#x} {v:#x}")
