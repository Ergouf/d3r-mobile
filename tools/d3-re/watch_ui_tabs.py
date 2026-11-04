"""Observe real mouse page tests without injecting any input.

Records navigation selection, all five pages' ancestor visibility, native
selector calls and native action-queue calls. Use one Frida session at a time.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import frida

from find_ui_object import fnv1a64
from probe_ui_tab_state import PAGE_NAMES
from version import assert_installed, js_consts

JS = js_consts() + r"""
const records=[], errors=[];
let registry=new Map(), pages=[], timer=null, last='', lastHeartbeat=0;
function q(a){return gm.add(a).readU64().toNumber();}
function u(a){return gm.add(a).readU32();}
function key(a){return gm.add(a).readU64().toString();}
function visible(obj){
  const seen=new Set();
  for(let i=0;obj&&i<64;i++){
    if(seen.has(obj)||!(u(obj+0x18)&4))return false;
    seen.add(obj);
    const parent=key(obj+0x38);
    if(parent==='18446744073709551615')return true;
    obj=registry.get(parent);
  }
  return false;
}
function state(){
  const navigation=q(q(0x9152080)), group=q(navigation+0x108), first=q(navigation);
  const current=group?u(group+0x18):null;
  return {navigation,group,first,selected:current,
    count64:group?key(group+8):null,player:group?u(group+0x1c):null,
    pages:pages.map(p=>({name:p.name,obj:p.obj,visible:visible(p.obj)}))};
}
function record(kind,data){
  if(records.length<10000)records.push({t:Date.now(),kind,...data});
}
function sample(){
  try{
    const s=state(), now=Date.now(), encoded=JSON.stringify(s);
    if(encoded!==last||now-lastHeartbeat>=1000){record('state',{state:s});last=encoded;lastHeartbeat=now;}
  }catch(e){if(errors.length<20)errors.push(String(e));}
}
rpc.exports={start(names){
  const world=q(q(0x914f840)+0x10), map=q(q(world+0xb80)), mask=u(map), buckets=q(map+0x10);
  if(mask>262143)throw new Error('invalid UI registry');
  for(let b=0;b<=mask;b++)for(let node=q(buckets+b*8),guard=0;node&&guard++<1024;node=q(node))
    registry.set(key(node+8),q(node+0x10));
  pages=names.map(([k,name])=>({name,obj:registry.get(k)||0}));
  if(pages.some(p=>!p.obj))throw new Error('missing character page');
  const selector=resolveGuest(0x816f550);
  if(!selector)throw new Error('native page selector does not resolve');
  Interceptor.attach(selector,{onEnter(args){
    try{
      if(args[1].toUInt32()!==0x816f550)return;
      const cpu=args[0];
      if(!cpu.add(0x350).readPointer().equals(gm))throw new Error('invalid CPU');
      record('selector',{args:[0,8,16,24].map(o=>cpu.add(o).readU64().toString()),state:state()});
    }catch(e){errors.push(String(e));}
  }});
  Interceptor.attach(base.add(RVA.native_action_press),{onEnter(args){
    record('native_action',{pad:args[0].toString()});
  }});
  sample();timer=setInterval(sample,100);
  return state();
},finish(){if(timer)clearInterval(timer);sample();return {records,errors};}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--stop-file", type=Path, required=True)
    args = ap.parse_args()
    if not 1 <= args.seconds <= 3600:
        ap.error("--seconds must be 1..3600")
    if args.stop_file.exists():
        ap.error("stop file already exists; use a fresh path")
    build = assert_installed()
    names = [[str(fnv1a64(("root.normallayer." + n).encode())), n] for n in PAGE_NAMES]
    started = datetime.now(timezone.utc).isoformat()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        print("READY", json.dumps(script.exports_sync.start(names)), flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and not args.stop_file.exists():
            time.sleep(0.2)
        result = script.exports_sync.finish()
    finally:
        session.detach()
    result.update(pid=args.pid, build=build, started_utc=started,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("SAVED", args.out, "records", len(result["records"]), "errors", result["errors"])


if __name__ == "__main__":
    main()
