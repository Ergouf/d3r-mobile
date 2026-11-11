import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function s(a){return gm.add(a).readS32();}
function cstr(a){
  try{
    const b=new Uint8Array(gm.add(a).readByteArray(80));
    let s="";
    for(let i=0;i<b.length && b[i];i++) s+=String.fromCharCode(b[i]);
    return s;
  }catch(e){return "ERR "+e.message;}
}
rpc.exports={read(){
  const a=0x15ee04858, b=0x15ee04a68;
  function snap(g){
    return {
      p10:q(g+0x10), u18:u(g+0x18), u48:s(g+0x48), u4c:s(g+0x4c),
      u68:q(g+0x68), u70:s(g+0x70), p30:q(g+0x30), p38:q(g+0x38)
    };
  }
  return {
    a:snap(a), b:snap(b),
    s1:cstr(0x8e2a879), s2:cstr(0x8e44db6),
    s3:cstr(0x8dcd52c), s4:cstr(0x8e09d1f), s5:cstr(0x8e10891), s6:cstr(0x8dfb7d0)
  };
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
print(data)
