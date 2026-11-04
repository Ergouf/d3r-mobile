import json
from pathlib import Path
import frida
from version import assert_installed, js_consts
tree=json.loads(Path(r"out/windows/kbm/session/round80-texts.json").read_text(encoding="utf-8"))["tree"]
comps=[t["obj"] for t in tree if t.get("vt")==0x90aab58]
print("comps", len(comps))
JS=js_consts()+r"""
function q(a){return gm.add(a).readU64().toNumber();}
rpc.exports={read(objs){
  return objs.map(o=>{
    let p78=0,p80=0,pA8=0,name=null;
    try{p78=q(o+0x78); p80=q(o+0x80); pA8=q(o+0xa8);}catch(e){}
    if(p78){
      try{
        const b=new Uint8Array(gm.add(p78).readByteArray(64));
        let s="";
        for(let i=0;i<b.length;i++){
          if(b[i]===0) break;
          if(b[i]>=32 && b[i]<127) s+=String.fromCharCode(b[i]);
          else s+=".";
        }
        name=s;
      }catch(e){name="err";}
    }
    return {o,p78,p80,pA8,name};
  });
}};
"""
assert_installed()
s=frida.get_local_device().attach(6032)
try:
    j=s.create_script(JS); j.load(); data=j.exports_sync.read(comps)
finally:
    s.detach()
Path(r"out/windows/kbm/session/round80-detail-items.json").write_text(json.dumps(data),encoding="utf-8")
for d in data:
    if d["p78"] or d["pA8"]:
        print(hex(d["o"]), "78", hex(d["p78"]), "80", hex(d["p80"]), "a8", hex(d["pA8"]), d["name"])
