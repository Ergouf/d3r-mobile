import frida, math
from version import assert_installed, js_consts
JS = js_consts() + r"""
function f(a){return gm.add(a).readFloat();}
function u(a){return gm.add(a).readU32();}
rpc.exports={read(){
  function dump(obj, lo, hi){
    const out=[];
    for(let off=lo; off<hi; off+=4){
      const v=f(obj+off);
      if(!Number.isFinite(v) || v===0) continue;
      if(Math.abs(v)>100000) continue;
      out.push([off, v]);
    }
    return out;
  }
  return {ring:dump(0x15d47f700, 0x100, 0x280), cursor:dump(0x158b79360, 0x100, 0x280)};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
for name, rows in data.items():
    print("==", name)
    for off,v in rows:
        print(f"  +{off:#x} {v:.4f}")
