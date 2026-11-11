"""Hook every vtable entry of a UI object's class and report which one a native A
press calls with that object as `this`.

Usage:
  python windows/d3-re/probe_button_vtable.py --pid 1234 --obj 0x15d... --pad 1
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
const out={calls:[],errors:[],hooked:[],presses:0},hooks=[];
function num(p){return p.readU64().toNumber();}
rpc.exports={
  arm(obj, size, pad){
    const vt=gm.add(obj).readU64().toNumber();
    for(let o=0;o<size;o+=8){
      let pc; try{pc=gm.add(vt+o).readU64().toNumber()}catch(e){break}
      if(!pc) continue;
      const host=resolveGuest(pc);
      if(!host) continue;
      out.hooked.push({off:o,pc:'0x'+pc.toString(16)});
      try {
        hooks.push(Interceptor.attach(host,{onEnter(args){
          if(parseInt(args[1].toString(),16)!==pc)return;
          const cpu=args[0];
          const self=num(cpu.add(0));
          if(self!==obj) return;
          const lr=num(cpu.add(240));
          out.calls.push({off:o,pc:'0x'+pc.toString(16),self:'0x'+self.toString(16),
                          x1:'0x'+num(cpu.add(8)).toString(16),x2:'0x'+num(cpu.add(16)).toString(16),
                          lr:'0x'+lr.toString(16)});
        }}));
      } catch(e) { out.errors.push('hook '+pc.toString(16)+': '+e.message); }
    }
    return {vt:'0x'+vt.toString(16), hooked:out.hooked.length};
  },
  press(pad){ out.presses++; return new NativeFunction(base.add(RVA.native_action_press),'int',['uint64'])(uint64(pad)); },
  stop(){ for(const h of hooks)h.detach(); return out; }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--size", type=lambda s: int(s, 0), default=0x140)
    ap.add_argument("--pad", type=lambda s: int(s, 0), default=1)
    ap.add_argument("--wait", type=float, default=3.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    s = frida.get_local_device().attach(args.pid)
    try:
        j = s.create_script(JS)
        errors = []
        j.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        j.load()
        armed = j.exports_sync.arm(args.obj, args.size, args.pad)
        time.sleep(0.5)
        pressed = j.exports_sync.press(args.pad)
        time.sleep(args.wait)
        data = j.exports_sync.stop()
        data["errors"].extend(errors)
    finally:
        s.detach()
    data.update(build=build, obj=args.obj, armed=armed, pressed=pressed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in data.items() if k != "hooked"}, indent=2))
    print("hooked", armed["hooked"])


if __name__ == "__main__":
    main()
