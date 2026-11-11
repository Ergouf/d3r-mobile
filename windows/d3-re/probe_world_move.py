"""Observe native movement consumers while an operator moves the player.

No guest calls, memory writes, or input injection. Hooks only exact guest entries.
The player is selected from the entity table by the camera target at startup.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
const out = {started: Date.now(), resolved: {}, counts: {}, samples: [], events: [],
             candidates: [], actions: [], errors: [], player: null};
const listeners = [];
const eventLast = {}, inputLast = {};
let lastSample = 0;
function num(p) { return p.readU64().toNumber(); }
function g64(a) { return num(gm.add(a)); }
function g32(a) { return gm.add(a).readU32(); }
function xyz(a) { return [0,4,8].map(o => gm.add(a+o).readFloat()); }
function hex(a) { return '0x' + a.toString(16); }
function elapsed() { return Date.now() - out.started; }
function err(name,e) { if (out.errors.length<20) out.errors.push(name+': '+e.message); }
function context(cpu) {
  const holder=g64(g64(0x914f8d0)), slot=g32(holder+12);
  const ro=num(cpu.add(808)), block=g64(ro+0x1f8);
  return {slot,ro,ctx:g64(block+0x80+slot*8)};
}
function table(ctx) {
  const a=g64(ctx), b=g64(a), c=g64(b+0x198), t=g64(c);
  return {t,limit:g32(t+0x100),shift:g32(t+0x168),buckets:g64(t+0x120)};
}
function entry(tab, id) {
  const i=id&0xffff;
  if(i>=tab.limit || tab.shift>16)return null;
  const base=g64(tab.buckets+Math.floor(i/(2**tab.shift))*8);
  const p=base+(i%(2**tab.shift))*0x360;
  return g32(p)===id?p:null;
}
function selectPlayer(ctx) {
  const tab=table(ctx), target=xyz(0x9862e68); let best=null;
  if(tab.limit>65536 || tab.shift>16)throw new Error('invalid table');
  for(let i=0;i<tab.limit;i++){
    const base=g64(tab.buckets+Math.floor(i/(2**tab.shift))*8);
    if(!base)continue;
    const p=base+(i%(2**tab.shift))*0x360,id=g32(p);
    if(!id || id===0xffffffff || (id&0xffff)!==i)continue;
    const pos=xyz(p+0x60),d=Math.hypot(...pos.map((v,k)=>v-target[k]));
    if(!best || d<best.distance)best={id,entry:p,pos,distance:d,ctx};
  }
  if(!best || best.distance>2)throw new Error('no player near camera target');
  out.player=best;
}
function sample(cpu) {
  if(elapsed()-lastSample<50)return; lastSample=elapsed();
  const tls=context(cpu);
  if(!out.player)selectPlayer(tls.ctx);
  const p=entry(table(tls.ctx),out.player.id); if(p===null)throw new Error('player handle expired');
  const dev=gm.add(0x97cd7a8);
  out.samples.push({ms:elapsed(),tid:Process.getCurrentThreadId(),ctx:hex(tls.ctx),
    entry:hex(p),pos:xyz(p+0x60),target:xyz(0x9862e68),camera:xyz(0x9862eac),
    buttons:dev.add(0x30).readU64().toString(),nativeBits:g32(0x9839ff8+0x370),
    axis:[dev.add(0x18).readS32(),dev.add(0x1c).readS32()],
    engine:[gm.add(0x9839ff8+0x37c).readFloat(),gm.add(0x9839ff8+0x380).readFloat()]});
}
function event(cpu,name,index) {
  const ev=num(cpu.add(index*8)); if(!ev)return;
  const type=g32(ev); if(type<0x19 || type>0x22)return;
  const payload=Array.from(new Uint8Array(gm.add(ev+0x30).readByteArray(0x28)));
  const sig=type+'|'+payload.join(','),key=name+'|'+Process.getCurrentThreadId();
  if(eventLast[key]===sig || out.events.length>=1200)return; eventLast[key]=sig;
  out.events.push({ms:elapsed(),name,tid:Process.getCurrentThreadId(),type,
    lr:hex(num(cpu.add(240))),words:Array.from(new Uint32Array(gm.add(ev).readByteArray(0x60)))});
}
function candidate(cpu) {
  const a=g64(g64(0x914f840)+0x10),s=g64(a+0xbb0);
  const words=Array.from(new Uint32Array(gm.add(s+0x378).readByteArray(0x38)));
  const key=Process.getCurrentThreadId(),sig=words.join(',');
  if(inputLast[key]===sig || out.candidates.length>=500)return;inputLast[key]=sig;
  out.candidates.push({ms:elapsed(),tid:key,state:hex(s),ctx:hex(context(cpu).ctx),words});
}
function action(cpu) {
  const lr=num(cpu.add(240));
  if(lr!==0x8128cf8 || out.actions.length>=500)return;
  const args=Array.from({length:8},(_,i)=>hex(num(cpu.add(i*8))));
  out.actions.push({ms:elapsed(),tid:Process.getCurrentThreadId(),lr:hex(lr),args});
}
function worldCommand(cpu) {
  if(out.actions.length>=1500)return;
  const args=Array.from({length:8},(_,i)=>num(cpu.add(i*8)));
  const path=args[3],sp=num(cpu.add(248));
  const bytes=Array.from(new Uint8Array(gm.add(path).readByteArray(28)));
  out.actions.push({ms:elapsed(),kind:'world_command',tid:Process.getCurrentThreadId(),
    lr:hex(num(cpu.add(240))),args:args.map(hex),path:bytes,
    stackArg:g32(sp),s0:cpu.add(280).readFloat(),s1:cpu.add(296).readFloat()});
}
for(const [name,pc,fn] of [
 ['hid',0x80fc310,c=>sample(c)],
 ['frame',0x82b9230,c=>{}],
 ['game_event',0x804f9c0,c=>event(c,'game_event',0)],
 ['event_map',0x80ce660,c=>event(c,'event_map',1)],
 ['game_dispatch',0x80cf3a0,c=>event(c,'game_dispatch',0)],
 ['candidate',0x8128b60,c=>candidate(c)],
 ['action',0x81565d0,c=>action(c)],
 ['world_command',0x80d21f0,c=>worldCommand(c)],
 ['script_submit',0x8828460,c=>{}]
]){
 const host=resolveGuest(pc);out.resolved[name]=host?host.toString():null;
 if(!host)continue;
 listeners.push(Interceptor.attach(host,{onEnter(args){
  if(parseInt(args[1].toString(),16)!==pc)return;
  const key=name+'|'+Process.getCurrentThreadId();out.counts[key]=(out.counts[key]||0)+1;
  try{fn(args[0]);}catch(e){err(name,e);}
 }}));
}
rpc.exports={data(){return out;},stop(){for(const l of listeners)l.detach();return out;}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--seconds", default=90.0, type=float)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--exercise", action="store_true", help="post W then D via the existing background diagnostic helper")
    args = ap.parse_args()
    assert_installed()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ready = args.out.with_suffix(".ready.json")
    stop = args.out.with_suffix(".stop")
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.on("message", lambda m, d: print(m, flush=True) if m.get("type") == "error" else None)
        script.load()
        ready.write_text(json.dumps({"pid": args.pid, "ready": True, "started": time.time()}), "utf-8")
        print("ready", ready, flush=True)
        if args.exercise:
            time.sleep(1.5)
            for key in ("w", "d"):
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                "windows/tools/Post-GameInput.ps1", "-ProcessId", str(args.pid),
                                "-Key", key, "-HoldMs", "1600"], check=True)
                time.sleep(1.5)
            stop.write_text("exercise complete", "utf-8")
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and not stop.exists():
            time.sleep(0.2)
        result = script.exports_sync.stop()
    finally:
        session.detach()
    args.out.write_text(json.dumps(result, indent=2), "utf-8")
    print(json.dumps({"player": result["player"], "counts": result["counts"],
                      "samples": len(result["samples"]), "errors": result["errors"]}), flush=True)


if __name__ == "__main__":
    main()
