"""Observe a single SDL UI click/key and its native business callbacks.

Assertions cover the requested destination focus/callback, absence of Npad
input, and (for pointer clicks) absence of global native confirm events.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida
import probe_pointer_click
import probe_sdl_key
import probe_ui_snapshot
from version import assert_installed, js_consts

JS=js_consts()+r"""
const out={calls:[],samples:[],errors:[],nativePresses:0},hooks=[];
function num(a){return a.readU64().toNumber();}
function q(a){return num(gm.add(a));}
function state(){
  const manager=q(q(q(0x914f840)+0x10)+0xb80),d=gm.add(0x97cd7a8);
  return {focus:gm.add(manager+0x50).readU64().toString(),
    npad:d.add(0x30).readU64().toString(),axis:[d.add(0x18).readS32(),d.add(0x1c).readS32()],
    bits:gm.add(0x9839ff8+0x370).readU32()};
}
for(const [name,pc] of [['select',0x838a6e0],['pause_action',0x8226850],['options',0x816f5c0],
                       ['main_menu',0x8366870]]){
 const host=resolveGuest(pc);if(!host)throw new Error('missing entry '+pc.toString(16));
 hooks.push(Interceptor.attach(host,{onEnter(args){
  if(parseInt(args[1].toString(),16)!==pc)return;
  this.cpu=args[0];this.lr=num(this.cpu.add(240));
  this.rec={name,lr:this.lr,args:[0,8,16].map(o=>num(this.cpu.add(o))),before:state()};out.calls.push(this.rec);
 },onLeave(){if(this.rec){this.rec.complete=num(this.cpu.add(256))===this.lr;this.rec.after=state();}}}));
}
hooks.push(Interceptor.attach(base.add(RVA.native_action_press),{onEnter(){out.nativePresses++;}}));
const hid=resolveGuest(0x80fc310);
hooks.push(Interceptor.attach(hid,{onEnter(args){if(parseInt(args[1].toString(),16)!==0x80fc310)return;
 try{out.samples.push(state());}catch(e){out.errors.push(e.message);}}}));
rpc.exports={state,stop(){for(const h of hooks)h.detach();return out;}};
"""


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid",type=int,required=True)
    action=ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--screen")
    action.add_argument("--key",choices=probe_sdl_key.KEYS)
    ap.add_argument("--expect-focus")
    ap.add_argument("--expect-call",choices=("options","pause_action","select","main_menu"))
    ap.add_argument("--expect-no-action",action="store_true")
    ap.add_argument("--expect-visible",help="exact UI control path that must become visible")
    ap.add_argument("--expect-hidden",help="exact UI control path that must become hidden")
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    build=assert_installed()
    session=frida.attach(args.pid)
    try:
        observe=session.create_script(JS);observe.load()
        before=observe.exports_sync.state()
        ui=session.create_script(probe_ui_snapshot.JS);ui.load()
        ui_names=probe_ui_snapshot.names_for(".") if args.expect_visible or args.expect_hidden else []
        wanted={n for n in (args.expect_visible,args.expect_hidden) if n}
        ui_names=[n for n in ui_names if n[1] in wanted]
        ui_before=ui.exports_sync.snapshot(ui_names,False)
        inject=session.create_script(probe_pointer_click.JS if args.screen else probe_sdl_key.JS)
        inject.load()
        if args.screen:
            pixel=[float(v) for v in args.screen.split(",")]
            if len(pixel)!=2 or not(0<=pixel[0]<1280 and 0<=pixel[1]<720):ap.error("invalid engine pixel")
            posted=inject.exports_sync.click(*pixel,1280,720)
        else:
            posted=inject.exports_sync.key(*probe_sdl_key.KEYS[args.key])
        time.sleep(2)
        after=observe.exports_sync.state()
        ui_after=ui.exports_sync.snapshot(ui_names,False)
        data=observe.exports_sync.stop()
    finally:
        session.detach()
    calls=data["calls"];samples=data["samples"]
    checks={"posted":bool(posted["down"] and posted["up"]),
      "neutral_npad":bool(samples) and all(s["npad"]=="0" and s["axis"]==[0,0] for s in samples),
      "complete":all(c.get("complete") for c in calls),"errors":not data["errors"]}
    if args.screen:
        checks["no_global_confirm"]=data["nativePresses"]==0
        checks["neutral_engine"]=bool(samples) and all(s["bits"]==0 for s in samples)
    if args.key=="alt":
        checks["no_unopened_wheel_action"]=data["nativePresses"]==0
    if args.expect_focus:checks["destination_focus"]=after["focus"]==args.expect_focus
    if args.expect_call:checks["business_callback"]=sum(c["name"]==args.expect_call for c in calls)==1
    if args.expect_no_action:
        checks["no_action"]=not any(c["name"]!="select" or c["lr"]==0 for c in calls) and before["focus"]==after["focus"]
    before_visible={o["name"] for o in ui_before["objects"]}
    after_visible={o["name"] for o in ui_after["objects"]}
    if args.expect_visible:
        checks["opened_control"]=args.expect_visible not in before_visible and args.expect_visible in after_visible
    if args.expect_hidden:
        checks["closed_control"]=args.expect_hidden in before_visible and args.expect_hidden not in after_visible
    summary={"pass":all(checks.values()),"checks":checks,"before":before,"after":after,
             "calls":{n:sum(c["name"]==n for c in calls) for n in {c["name"] for c in calls}}}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps({"build":build,"pid":args.pid,"input":posted,"summary":summary,
        "ui_before":ui_before,"ui_after":ui_after,**data},indent=2),"utf-8")
    print(json.dumps(summary,indent=2))
    if not summary["pass"]:raise SystemExit(1)


if __name__=="__main__":
    main()
