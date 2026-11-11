"""Dump one live UI object's fields and vtable entries.

Usage:
  python windows/d3-re/probe_ui_object.py --pid 1234 --obj 0x15e9f7fc0 --bytes 0x300
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports={dump(obj, size){
  const vt=gm.add(obj).readU64().toNumber();
  const words=[];
  for(let o=0;o<size;o+=8){
    let v; try{v=gm.add(obj+o).readU64()}catch(e){break}
    words.push({off:o, value:v.toString(), hex:'0x'+v.toString(16)});
  }
  const entries=[];
  for(let o=0;o<0x140;o+=8){
    let v; try{v=gm.add(vt+o).readU64().toNumber()}catch(e){break}
    entries.push({off:o, pc:'0x'+v.toString(16)});
  }
  return {obj, vt:'0x'+vt.toString(16), words, vtable:entries};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--bytes", type=lambda s: int(s, 0), default=0x300)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        data = script.exports_sync.dump(args.obj, args.bytes)
    finally:
        session.detach()
    data["build"] = build
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("vt", data["vt"])
    print("vtable:", " ".join(f"{e['off']:x}:{e['pc']}" for e in data["vtable"] if e["pc"] != "0x0"))
    print("fields:")
    for w in data["words"]:
        v = int(w["hex"], 16)
        if 0x10000000 <= v < 0x200000000 or v < 0x10000:
            print(f"  +{w['off']:03x} {w['hex']}")


if __name__ == "__main__":
    main()
