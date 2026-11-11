import json, frida
from pathlib import Path
from version import assert_installed, js_consts
JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports={read(){
  function words(p, n){
    const out=[];
    for(let i=0;i<n;i++){ try{out.push(q(p+i*8));}catch(e){out.push(0);} }
    return out;
  }
  function ascii(p, n){
    try{
      const b=new Uint8Array(gm.add(p).readByteArray(n));
      let s="";
      for(let i=0;i<b.length;i++){
        const c=b[i];
        if(c===0) break;
        if(c<32||c>126) return null;
        s+=String.fromCharCode(c);
      }
      return s.length>=4 ? s : null;
    }catch(e){return null;}
  }
  const base=0x15aecf660;
  const ws=words(base, 48);
  const strs=[];
  for(let i=0;i<ws.length;i++){
    const p=ws[i];
    if(p<0x100000 || p>0x8000000000) continue;
    const s=ascii(p, 48);
    if(s) strs.push({off:i*8, p, s});
  }
  // scan equipped panel object and 0x1800 bytes for item pointers
  const targets=[0x15aecf6f0,0x15aed0070,0x15aecfe10,0x15aecf660,0x15aecffe0];
  const eq=0x15d7b2e00;
  const hits=[];
  const buf=new Uint8Array(gm.add(eq).readByteArray(0x1800));
  const dv=new DataView(buf.buffer);
  for(let off=0; off<=buf.length-8; off+=8){
    const p=dv.getUint32(off+4,true)*0x100000000 + dv.getUint32(off,true);
    if(targets.includes(p)) hits.push({off, p});
  }
  // vtable of component
  const vt=0x90aab58;
  const methods=[];
  for(let i=0;i<24;i++) methods.push(q(vt+i*8));
  return {ws, strs, hits, methods, compVt:q(0x158b7b980)};
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read()
finally:
    s.detach()
Path(r"out/windows/kbm/session/round81-item.json").write_text(json.dumps(data), encoding="utf-8")
print("comp vt", hex(data["compVt"]))
print("strings", data["strs"])
print("eq hits", [(hex(h["off"]), hex(h["p"])) for h in data["hits"]])
print("methods")
for i,m in enumerate(data["methods"]):
    print(f"  +{i*8:#x} {m:#x}")
print("words")
for i,w in enumerate(data["ws"]):
    if w: print(f"  +{i*8:#x} {w:#x}")
