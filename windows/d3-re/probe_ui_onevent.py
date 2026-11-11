"""Log UI widget OnEvent calls (0x83BAD40) around native action presses."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
const out={calls:[],errors:[],started:Date.now()};
const host=resolveGuest(0x83BAD40);
if(!host) throw new Error('no guest entry for widget OnEvent');
const h=Interceptor.attach(host,{onEnter(args){
  try{
    const cpu=args[0];
    const w=cpu.add(0).readPointer().toString();
    const evGuest=parseInt(cpu.add(8).readPointer().toString(),16);
    const ev=gm.add(evGuest);
    const type=evGuest?ev.readU32():-1;
    let player=-1,button=-1,value=-1;
    try{player=ev.add(0x28).readS32();}catch(e){}
    try{button=ev.add(0x2c).readS32();}catch(e){}
    try{value=ev.add(0x44).readS32();}catch(e){}
    const lr=cpu.add(30*8).readPointer().toString();
    if(type!==0 && out.calls.length<300) out.calls.push({ms:Date.now()-out.started,w,type,player,button,value,lr});
  }catch(e){if(out.errors.length<5)out.errors.push(e.message+' @ '+(e.stack||''));}
}});
rpc.exports={press(pad){return new NativeFunction(base.add(RVA.native_action_press),'int',['uint64'])(uint64(pad));},
 stop(){h.detach();return out;}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=1.5)
    ap.add_argument("--press", type=lambda s: int(s, 0))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        errors = []
        script.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        script.load()
        time.sleep(0.3)
        pressed = script.exports_sync.press(args.press) if args.press is not None else None
        time.sleep(args.seconds)
        result = script.exports_sync.stop()
        result["errors"].extend(errors)
    finally:
        session.detach()
    result.update(build=build, press=args.press, pressed=pressed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), "utf-8")
    print("calls", len(result["calls"]), "errors", result["errors"])
    for c in result["calls"][:40]:
        print(c)


if __name__ == "__main__":
    main()
