"""Trace one live UI list, its row widgets, ancestors and model.

The default is observation only. Optional SDL click and native A are separate,
timestamped diagnostic phases; neither changes window focus or writes Npad.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from probe_pointer_click import JS as CLICK_JS
from version import assert_installed, js_consts

JS = js_consts() + r"""
const out={objects:[],hooked:[],calls:[],counts:{},markers:[],errors:[]};
const hooks=[], targets=new Map(), methods=new Map();
let phase='baseline';
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function bytes(a,n){try{return hexBytes(a,n)}catch(e){return 'error:'+e.message}}
function event(a){
  if(!a)return null;
  try{return {ptr:a,type:u(a),player:u(a+0x28),button:u(a+0x2c),bytes:bytes(a,0x40)}}catch(e){return null}
}
function addMethod(pc,self,label,isEvent){
  if(!resolveGuest(pc))return;
  if(!methods.has(pc))methods.set(pc,[]);
  methods.get(pc).push({self,label,isEvent});
}
function addObject(obj,label,model=false){
  if(!obj||targets.has(obj))return;
  targets.set(obj,label);
  const vt=q(obj), snap={obj,label,vt,fields:{},slots:[]};
  if(!model)for(const off of [0x30,0x38,0x118,0x1e0,0x1e4,0x210,0x218,0x230,0x238,0x240,0x248,0x250,0x258,0x2a4]){
    try{snap.fields[off]='0x'+gm.add(obj+off).readU64().toString(16)}catch(e){}
  }
  const size=model?0x80:0x110;
  for(let off=0;off<size;off+=8){
    const pc=q(vt+off);
    if(!resolveGuest(pc))continue;
    snap.slots.push({off,pc});
    addMethod(pc,obj,label+'+vt'+off.toString(16),!model&&(off===0x60||off===0xe0));
  }
  if(!model){
    const changed=q(obj+0x240);
    if(obj===listObj&&changed)addMethod(changed,obj+0x30,label+'+240',false);
    const table=q(obj+0x118);
    if(table)for(let off=0;off<0x40;off+=8){
      try{const pc=q(table+off);if(resolveGuest(pc))addMethod(pc,obj+0x30,label+'+118['+off+']',false)}catch(e){}
    }
  }
  out.objects.push(snap);
}
let listObj=0;
rpc.exports={
  arm(obj){
    listObj=obj;
    const global=q(0x914f840),world=q(global+0x10),map=q(q(world+0xb80));
    const mask=u(map),buckets=q(map+0x10),registry=new Map();
    if(mask>262143)throw new Error('invalid registry');
    for(let i=0;i<=mask;i++)for(let n=q(buckets+i*8),guard=0;n&&guard++<1024;n=q(n)){
      registry.set(gm.add(n+8).readU64().toString(),q(n+0x10));
    }
    addObject(obj,'list');
    const count=u(obj+0x218),rows=q(obj+0x210);
    if(count>128)throw new Error('unexpected row count');
    for(let i=0;i<count;i++)addObject(registry.get(gm.add(rows+i*8).readU64().toString()),'row'+i);
    let parent=obj;
    for(let i=0;i<16;i++){
      parent=registry.get(gm.add(parent+0x38).readU64().toString());
      if(!parent)break;
      addObject(parent,'parent'+i);
    }
    const subs=q(q(world+0xb80)+0x10),entries=q(subs),subCount=u(subs+8);
    if(subCount>1024)throw new Error('invalid subscribers');
    for(let i=0;i<subCount;i++){
      const sub=q(entries+i*8),vt=q(sub);
      if(q(vt+0xb0)===0x83b81f0)addObject(sub,'subscriber'+i);
    }
    addObject(q(obj+0x258),'model',true);
    for(const [pc,specs] of methods){
      const host=resolveGuest(pc);
      out.hooked.push({pc,specs});
      hooks.push(Interceptor.attach(host,{
        onEnter(args){
          if(parseInt(args[1].toString(),16)!==pc)return;
          const cpu=args[0],self=cpu.readU64().toNumber();
          const matched=specs.filter(s=>s.self===self);
          if(!matched.length)return;
          const x1=cpu.add(8).readU64().toNumber(),x2=cpu.add(16).readU64().toNumber();
          const ev=matched.some(s=>s.isEvent)?event(x1):null;
          const raw=ev&&ev.type===1?event(x2):null;
          const key=[phase,pc,self,ev?ev.type:'',raw?raw.type:'',raw?raw.button:''].join(':');
          out.counts[key]=(out.counts[key]||0)+1;
          if(out.counts[key]>3||out.calls.length>=8192)return;
          const rec={phase,ms:Date.now(),pc,self,labels:matched.map(s=>s.label),x1,x2,
                     x3:cpu.add(24).readU64().toNumber(),lr:cpu.add(240).readU64().toNumber(),ev,raw};
          out.calls.push(rec);this.record=rec;this.cpu=cpu;this.lr=rec.lr;
        },
        onLeave(){
          if(this.record&&this.cpu.add(256).readU64().toNumber()===this.lr){
            this.record.returned=true;this.record.ret=this.cpu.readU64().toNumber();
          }
        }
      }));
    }
    out.markers.push({phase,ms:Date.now()});
    return {objects:out.objects.length,methods:out.hooked.length};
  },
  mark(name){phase=name;out.markers.push({phase,ms:Date.now()});},
  native(){return new NativeFunction(base.add(RVA.native_action_press),'int',['uint64'])(uint64(1));},
  stop(){for(const h of hooks)h.detach();return out;}
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--obj", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--click", help="optional engine pixels x,y")
    ap.add_argument("--native-a", action="store_true", help="diagnostic only, after click phase")
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    data = {"build": build, "pid": args.pid, "obj": args.obj}
    session = frida.get_local_device().attach(args.pid)
    errors = []
    try:
        script = session.create_script(JS)
        script.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        script.load()
        data["armed"] = script.exports_sync.arm(args.obj)
        time.sleep(args.seconds)
        if args.click:
            x, y = (float(v) for v in args.click.split(","))
            if not (0 <= x < 1280 and 0 <= y < 720):
                raise ValueError("click outside viewport")
            click = session.create_script(CLICK_JS)
            click.load()
            script.exports_sync.mark("click")
            data["click"] = click.exports_sync.click(x, y, 1280, 720)
            time.sleep(args.seconds)
        if args.native_a:
            script.exports_sync.mark("native-A")
            data["native_return"] = script.exports_sync.native()
            time.sleep(args.seconds)
        data["trace"] = script.exports_sync.stop()
        data["trace"]["errors"].extend(errors)
    finally:
        session.detach()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    print(json.dumps({"objects": data["armed"], "calls": len(data["trace"]["calls"]),
                      "markers": data["trace"]["markers"], "errors": data["trace"]["errors"]}, indent=2))


if __name__ == "__main__":
    main()
