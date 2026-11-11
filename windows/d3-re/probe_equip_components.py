"""Compare equipment slot components with the detail-panel component."""
from __future__ import annotations
import json
from pathlib import Path
import frida
from version import assert_installed, js_consts

JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports={read(objs){
  return objs.map(obj=>{
    const words=[];
    for(let off=0; off<0x180; off+=8){
      let v=0; try{v=q(obj+off);}catch(e){v=-1;}
      words.push(v);
    }
    return {obj, vt:q(obj), words};
  });
}};
"""

def main():
    assert_installed()
    # detail first child, armleft component, head component from earlier prints
    # head component address from snapshot
    snap=json.loads(Path(r"out/windows/kbm/session/round80-equip-snapshot.json").read_text(encoding="utf-8"))
    head=next(b for b in snap["buttons"] if b["name"].endswith("button_head"))
    torso=next(b for b in snap["buttons"] if b["name"].endswith("button_torso"))
    objs=[0x1598f9820, 0x158b7b980, head["children"][0]["child"], torso["children"][0]["child"]]
    s=frida.get_local_device().attach(6032)
    try:
        j=s.create_script(JS); j.load(); data=j.exports_sync.read(objs)
    finally:
        s.detach()
    labels=["detail","armleft","head","torso"]
    Path(r"out/windows/kbm/session/round80-components.json").write_text(json.dumps(data),encoding="utf-8")
    # print fields that differ and look like pointers or small ids
    base=data[0]["words"]
    print("label", labels)
    print("objs", [hex(o) for o in objs])
    for i,w in enumerate(base):
        vals=[d["words"][i] for d in data]
        if len(set(vals))==1 and vals[0] in (0, 0xffffffffffffffff):
            continue
        if len(set(vals))==1:
            continue
        off=i*8
        print(f"+{off:#05x} " + " ".join(f"{v:#x}" for v in vals))

if __name__=="__main__":
    main()
