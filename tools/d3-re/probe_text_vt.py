import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
rpc.exports={read(){
  const vt=0x90ae520; const e=[];
  for(let i=0;i<40;i++) e.push(q(vt+i*8));
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
    if v and (v & 3)==0 and 0x8000000 < v < 0x9000000:
        print(f"+{i*8:#x} {v:#x}")
    else:
        print(f"+{i*8:#x} {v:#x} ?")
        if i>30: break
