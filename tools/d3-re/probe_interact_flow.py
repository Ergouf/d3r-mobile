"""Observe native target selection/interaction commands (optional native press)."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
const out={calls:[],errors:[],counts:{},started:Date.now()},hooks=[];
const businessOnly=false;
function num(p){return p.readU64().toNumber();}
function bytes(a,n){try{return hexBytes(a,n);}catch(e){return e.message;}}
for(const [name,pc] of [
 ['select',0x8524100],['resolve',0x80d5af0],['targeting',0x840a4f0],
 ['action',0x80cba30],['prepare',0x80c5710],['submit',0x80c7270],
 ['world',0x80d21f0],['event',0x82bebb0]
]){
 if(businessOnly&&!['resolve','action','prepare','submit'].includes(name))continue;
 const host=resolveGuest(pc);if(!host)continue;
 hooks.push(Interceptor.attach(host,{
  onEnter(args){
   if(parseInt(args[1].toString(),16)!==pc)return;
   const cpu=args[0];
   if(!cpu.add(0x350).readPointer().equals(gm))return;
   const a=Array.from({length:8},(_,i)=>num(cpu.add(i*8)));
   out.counts[name]=(out.counts[name]||0)+1;
   if(out.calls.length>=500)return;
   const r={name,pc,ms:Date.now()-out.started,tid:this.threadId,lr:num(cpu.add(240)),args:a,
     s:[cpu.add(280).readFloat(),cpu.add(296).readFloat()],stack:bytes(num(cpu.add(248)),32)};
   if(name==='action')r.record=bytes(a[1],64);
   if(['prepare','world','submit'].includes(name))r.path=bytes(a[name==='submit'?4:3],28);
   if(name==='select')r.selection=bytes(a[0],64);
   if(name==='event' && a[2]<=512)r.event=bytes(a[1],a[2]);
   out.calls.push(r);this.rec=r;this.cpu=cpu;this.lr=r.lr;
  },onLeave(){if(!this.rec)return;this.rec.complete=num(this.cpu.add(256))===this.lr;
    this.rec.ret=num(this.cpu);}
 }));
}
hooks.push(Interceptor.attach(base.add(RVA.native_action_press),{onEnter(args){
 out.counts.native_action=(out.counts.native_action||0)+1;
 out.calls.push({name:'native_action',ms:Date.now()-out.started,pad:args[0].toString()});
}}));
rpc.exports={press(pad){return new NativeFunction(base.add(RVA.native_action_press),'int',['uint64'])(uint64(pad));},
 stop(){for(const h of hooks)h.detach();return out;}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--press", type=lambda s:int(s,0))
    ap.add_argument("--business-only", action="store_true",
                    help="omit frame/event/world hooks so idle traffic cannot fill the bounded call log")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe" for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is no longer running")
    if not 0 <= args.seconds <= 60:
        ap.error("--seconds must be between 0 and 60")
    s = device.attach(args.pid)
    try:
        j = s.create_script(JS.replace("const businessOnly=false;",
                                      "const businessOnly=true;" if args.business_only else
                                      "const businessOnly=false;"))
        errors = []
        j.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        j.load()
        time.sleep(0.5)
        pressed = j.exports_sync.press(args.press) if args.press is not None else None
        time.sleep(args.seconds)
        result = j.exports_sync.stop()
        result["errors"].extend(errors)
    finally:
        s.detach()
    result.update(build=build, press=args.press, pressed=pressed, business_only=args.business_only)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), "utf-8")
    print(result["counts"], "errors", result["errors"])
    for r in result["calls"]:
        if r["name"] not in ("event", "targeting"): print(r)


if __name__ == "__main__":
    main()
