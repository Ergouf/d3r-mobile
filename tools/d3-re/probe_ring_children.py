"""Read live inventory ring child order and match named button objects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts


JS = js_consts() + r"""
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
rpc.exports={read(ring){
  const data=q(ring+0x60), count=u(ring+0x68);
  if(count<2||count>40) throw new Error('ring child count '+count);
  const rows=[];
  for(let i=0;i<count;i++){
    const ref=data+i*24, obj=q(ref+8), vt=q(obj);
    rows.push({index:i,ref,obj,vt,key:gm.add(obj+0x30).readU64().toString(),
      parent:gm.add(obj+0x38).readU64().toString(),
      rect:[0x88,0x8c,0x90,0x94].map(o=>gm.add(obj+o).readFloat()),
      enabled:u(obj+0x3c8),hitMode:u(obj+0x1b0),callback:q(obj+0x118),
      predicate:q(obj+0x488),event:q(vt+0x60)});
  }
  return {ring,data,count,rows};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, default=6032)
    ap.add_argument("--ring", type=lambda s: int(s, 0), default=0x15d47f700)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.read(args.ring)
    finally:
        session.detach()
    names = json.loads(Path("out/windows/kbm/session/round80-ring-named.json").read_text(encoding="utf-8"))
    by_obj = {item["obj"]: item["name"].split(".")[-1] for item in names["objects"]}
    for row in result["rows"]:
        row["name"] = by_obj.get(row["obj"])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for row in result["rows"]:
        print(row["index"], row["name"], hex(row["obj"]), [round(v) for v in row["rect"]])


if __name__ == "__main__":
    main()
