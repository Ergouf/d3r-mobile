"""Query the native UI virtual hit-test at an engine pixel (no activation)."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_guest_call as bridge
from find_ui_object import fnv1a64
from version import assert_installed

EXTENSION = r"""
function u64(a){return gp(a).readU64().toNumber();}
function u32(a){return gp(a).readU32();}
function uiPointer(cpu,req){
  const sp=cpu.add(248).readU64().toNumber(),pixel=sp-0x20000,ref=pixel+0x40;
  const manager=u64(u64(u64(0x914f840)+0x10)+0xb80),roots=u64(manager+0x10);
  const data=u64(roots),count=u32(roots+8),map=u64(manager),mask=u32(map),buckets=u64(map+0x10);
  gp(pixel).writeS32(req.screen[0]);gp(pixel+4).writeS32(req.screen[1]);
  callGuest(cpu,0x8350bf0,[pixel,pixel+0x20],null,null);
  const out={ok:true,manager,roots,count,screen:req.screen,
    point:[gp(pixel+0x20).readFloat(),gp(pixel+0x24).readFloat()],hits:[]};
  if(count>1024)throw new Error('invalid active UI root list');
  const objects=new Map();
  for(let b=0;b<=mask;b++)for(let n=u64(buckets+b*8),k=0;n&&k++<1024;n=u64(n))
    objects.set(gp(n+8).readU64().toString(),u64(n+0x10));
  out.fields=Array.from({length:14},(_,i)=>gp(manager+i*8).readU64().toString());
  const rootList=req.rootKey?[objects.get(req.rootKey)]:req.obj?[req.obj]:Array.from({length:count},(_,i)=>u64(data+i*8));
  for(let i=0;i<rootList.length;i++){
    const root=rootList[i];if(!root)continue;
    const vt=u64(root),pc=u64(vt+0x78);
    gp(ref).writeByteArray(new Uint8Array(32));
    const r=callGuest(cpu,pc,[root,pixel],ref,null);
    const key=gp(ref).readU64().toString(),object=objects.get(key);
    const hit={i,root,rootKey:gp(root+0x30).readU64().toString(),
      children:u32(root+0x68),flags:u32(root+0x18),key,object,pc,call:r};
    if(object){
      const v=u64(object);hit.vt=v;hit.methods=Array.from({length:20},(_,j)=>u64(v+j*8));
      hit.rect=[0x88,0x8c,0x90,0x94].map(o=>gp(object+o).readFloat());
      hit.callbacks=hexBytes(u64(object+0x118),0x150);
    }
    out.hits.push(hit);
  }
  return out;
}
"""


def build_js() -> str:
    js = bridge.JS.replace("__CONTEXT__","null").replace("__FRAME__","0x80fc310")
    js = js.replace("__AFTER__","true").replace("__EVENT__","null")
    js = js.replace("function runCall(cpu, req) {",EXTENSION+"\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
        "if (req.mode === 'ui-pointer') { result = uiPointer(cpu,req); } else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid",type=int,required=True)
    ap.add_argument("--screen",required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--name",help="query a specific top-level UI path instead of input subscribers")
    ap.add_argument("--obj",type=lambda s:int(s,0),help="hit-test one object instead of the root list")
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(build_js())
        script.load()
        script.exports_sync.arm({"mode":"ui-pointer","screen":[int(v) for v in args.screen.split(",")],
          "rootKey":str(fnv1a64(args.name.lower().encode())) if args.name else None,
          "obj":args.obj})
        deadline = time.monotonic()+10
        data = {}
        while time.monotonic()<deadline:
            data = script.exports_sync.result()
            if data.get("result"):
                break
            time.sleep(.1)
    finally:
        session.detach()
    data["build"] = build
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(data,indent=2),"utf-8")
    result = data.get("result") or {}
    print("UI point",result.get("point"))
    for hit in result.get("hits",[]):
        print({k:v for k,v in hit.items() if k not in ("methods","callbacks","call")})


if __name__ == "__main__":
    main()
