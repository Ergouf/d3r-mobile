import json, frida
from pathlib import Path
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function s(a){return gm.add(a).readS32();}
rpc.exports={read(){
  function slots(vt, n){const a=[]; for(let i=0;i<n;i++) a.push(q(vt+i*8)); return a;}
  function dump(g, n){
    const words=[];
    for(let i=0;i<n;i++){
      const v=q(g+i*8);
      words.push(v);
    }
    return words;
  }
  const a=0x15ee04858, b=0x15ee04a68;
  return {
    vtA:q(a), vtB:q(b),
    methodsA:slots(q(a), 28),
    methodsB:slots(q(b), 28),
    wordsA:dump(a, 40),
    wordsB:dump(b, 40)
  };
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
Path(r"out/windows/kbm/session/round82-embed.json").write_text(json.dumps(data), encoding="utf-8")
print("vtA", hex(data["vtA"]), "vtB", hex(data["vtB"]))
print("methodsA")
for i,m in enumerate(data["methodsA"]):
    print(f"  +{i*8:#04x} {m:#x}")
print("methodsB")
for i,m in enumerate(data["methodsB"]):
    print(f"  +{i*8:#04x} {m:#x}")
print("wordsA")
for i,w in enumerate(data["wordsA"]):
    tag=""
    if 0x150000000 < w < 0x170000000 or 0x8000000 < w < 0x9200000: tag=" PTR"
    elif w < 32: tag=" small"
    print(f"  +{i*8:#04x} {w:#x}{tag}")
