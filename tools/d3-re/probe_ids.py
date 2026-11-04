import frida
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function s(a){return gm.add(a).readS32();}
rpc.exports={read(){
  function dump(g){
    const vt=q(g);
    const methods=[];
    for(let i=0;i<16;i++) methods.push(q(vt+i*8));
    const words=[];
    for(let i=0;i<16;i++) words.push(q(g+i*8));
    const ints=[];
    for(let i=0;i<32;i++) ints.push(s(g+i*4));
    return {g, vt, methods, words, ints};
  }
  return {a:dump(0x15ee03da8), b:dump(5886723728)};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
for name in ("a","b"):
    d=data[name]
    print(name, "g", hex(d["g"]), "vt", hex(d["vt"]))
    print(" methods", " ".join(hex(m) for m in d["methods"]))
    print(" words")
    for i,w in enumerate(d["words"]):
        print(f"  +{i*8:#x} {w:#x}")
    print(" ints", d["ints"][:24])
