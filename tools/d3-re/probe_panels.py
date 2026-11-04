import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports={read(){
  const base=ptr('0x1b9c44d0000');
  const size=805306368;
  const pats=[['inv','60 00 0b 09 00 00 00 00'],['gen','e0 ae 0a 09 00 00 00 00']];
  const found={};
  for(const [name,pat] of pats){
    const hits=Memory.scanSync(base, size, pat);
    found[name]=hits.slice(0,30).map(h=>{
      const g=parseInt(h.address.sub(gm).toString(),16);
      return {g, w18:u(g+0x18), id:u(g+0xc)>>>0, p138:q(g+0x138), p140:q(g+0x140)};
    });
    found[name+'n']=hits.length;
  }
  return found;
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
for k in ("inv","gen"):
    print(k, "n", data[k+"n"])
    for rec in data[k]:
        print(" ", {a:hex(b) for a,b in rec.items()})
