"""Read UI jump tables and hunt item-name bytes in the equipped panel."""
from __future__ import annotations
import json
from pathlib import Path
import frida
from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function s32(a){return gm.add(a).readS32();}
function targets(base, n){
  const out=[];
  for(let i=0;i<n;i++){
    const rel=s32(base+i*4);
    out.push({i, rel, pc:(base+rel)>>>0});
  }
  return out;
}
function hunt(obj){
  const hits=[];
  const bytes=new Uint8Array(gm.add(obj).readByteArray(0x480));
  for(let i=0;i+2<bytes.length;i++){
    if(bytes[i]===0xe7 && bytes[i+1]===0xae && bytes[i+2]===0x80) hits.push({kind:'inline', off:i});
  }
  for(let off=0; off<0x480; off+=8){
    let p=0;
    try{ p=q(obj+off);}catch(e){continue;}
    if(p<0x100000 || p>0x8000000000) continue;
    try{
      const b=new Uint8Array(gm.add(p).readByteArray(24));
      let s='';
      for(let k=0;k<b.length && b[k];k++) s+=String.fromCharCode(b[k]);
      if(s.length>=4 && /[\x20-\x7e]/.test(s[0])) hits.push({kind:'ptr', off, p, ascii:s.slice(0,24)});
      if(b[0]===0xe7 && b[1]===0xae) hits.push({kind:'utf8', off, p});
    }catch(e){}
  }
  return hits;
}
rpc.exports={read(){
  const samples=[0x15d841fc0,0x15d8425e0,0x15d842b00,0x15d843160,0x15d6c5200,0x15d6c8140];
  return {
    tableA: targets(0x8ebf830, 16),
    tableB: targets(0x8ec136c, 16),
    hunts: samples.map(obj=>({obj, hits:hunt(obj)}))
  };
}};
"""

def main():
    assert_installed()
    s=frida.get_local_device().attach(6032)
    try:
        j=s.create_script(JS); j.load(); data=j.exports_sync.read()
    finally:
        s.detach()
    Path(r"out/windows/kbm/session/round80-jump.json").write_text(json.dumps(data,indent=1),encoding="utf-8")
    print("handler 0x8375e70 table")
    for e in data["tableA"]:
        print(f"  w2={e['i']:2d} -> {e['pc']:#x}")
    print("inventory 0x842b280 table")
    for e in data["tableB"]:
        print(f"  w2={e['i']:2d} -> {e['pc']:#x}")
    for h in data["hunts"]:
        print(hex(h["obj"]), h["hits"][:8], "n", len(h["hits"]))

if __name__=="__main__":
    main()
