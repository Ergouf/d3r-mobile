"""Inspect world targets, native paths and candidate interaction resolution.

Runs after the player-0 world callback, on an isolated CPU and guest stack.
Default mode only reads entities and asks the game's projection functions.
--resolve explicitly calls an unvalidated action-selection candidate; it does
not submit an action, but that engine function may update internal caches.
No Npad, foreground window, hardware input or screenshots are used.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_guest_call as bridge
from version import assert_installed

EXTENSION = r"""
function g32(a) { return gp(a).readU32(); }
function g64(a) { return gp(a).readU64().toNumber(); }
function xyz(a) { return [0,4,8].map(o=>gp(a+o).readFloat()); }
function hx(a) { return '0x'+a.toString(16); }
function lookup(tab,id,stride) {
  const i=id&0xffff, n=g32(tab+0x100), shift=g32(tab+0x168);
  if(i>=n || shift>16) return null;
  const b=g64(g64(tab+0x120)+(i>>shift)*8);
  const p=b+(i&((1<<shift)-1))*stride;
  return g32(p)===id?p:null;
}
function scene(cpu, req) {
  const player=callGuest(cpu,0x8525360,[0],null,null).ret;
  if(!player) throw new Error('local player not active');
  const actor=g32(player+4), ctx=liveContext(cpu,SLOT);
  const table=g64(g64(g64(g64(ctx))+0x198));
  const ent=lookup(table,actor,0x360);
  if(!ent)throw new Error('local player handle expired');
  const world=g64(g64(0x914f840)+16), ctrlId=g32(player+8);
  const controller=lookup(g64(world+0xa98),ctrlId,0x410);
  if(!controller || g32(controller+8)!==actor)throw new Error('controller mismatch');
  const sp=cpu.add(248).readU64().toNumber(), scratch=sp-0x20000;
  const pos=xyz(ent+0x60), n=g32(table+0x100), shift=g32(table+0x168), buckets=g64(table+0x120);
  if(n>65536 || shift>16)throw new Error('invalid table');
  const out={ok:true,ctx:hx(ctx),player:hx(player),actor:hx(actor),entity:hx(ent),
    controller:hx(controller),pos,place:g32(ent+0xa0),selection:hexBytes(player+0xdb74,0x50),
    state:hexBytes(player+0xe880,0xc0),entities:[]};
  if(req.screen) {
    gp(scratch).writeS32(req.screen[0]);gp(scratch+4).writeS32(req.screen[1]);
    gp(scratch+0x100).writeByteArray(new Uint8Array(256));
    const picked=callGuest(cpu,0x813e6a0,[scratch,scratch+0x100,req.mask,0xffffffff,
      scratch+0x110,scratch+0x114,scratch+0x118,scratch+0x11c],null,null);
    out.pick={screen:req.screen,mask:req.mask,call:picked,position:xyz(scratch+0x100),
      fields:[0x110,0x114,0x118].map(o=>hx(g32(scratch+o))),distance:gp(scratch+0x11c).readFloat()};
  }
  for(let i=0;i<n;i++) {
    const bucket=g64(buckets+(i>>shift)*8); if(!bucket)continue;
    const e=bucket+(i&((1<<shift)-1))*0x360, id=g32(e);
    if(!id || id===0xffffffff || (id&0xffff)!==i)continue;
    const p=xyz(e+0x60),distance=Math.hypot(...p.map((v,k)=>v-pos[k]));
    if(!Number.isFinite(distance) || distance>req.radius)continue;
    const type=g32(e+0x14c),sno=g32(e+0x18);
    for(let k=0;k<3;k++)gp(scratch+k*4).writeFloat(p[k]);
    gp(scratch+12).writeU32(g32(e+0xa0));
    callGuest(cpu,0x826ca70,[scratch,scratch+0x100,0xffffffff],null,null);
    const screen=xyz(scratch+0x100).slice(0,2);
    let def=null;
    if(req.defs) {
      const manager=g64(g64(0x9150778));
      const data=callGuest(cpu,0x86c8bb0,[manager,sno,0],null,null).ret;
      def={address:hx(data),bytes:hexBytes(data,0x90)};
      gp(scratch+0x400).writeU64(data);
      callGuest(cpu,0x86c8db0,[manager,scratch+0x400],null,null);
    }
    out.entities.push({id:hx(id),entry:hx(e),type,sno,pos:p,distance,screen,
      place:g32(e+0xa0),gizmo:gp(e+0x148).readS32(),flags:gp(e+0x160).readU16(),bytes:hexBytes(e,0x60),def});
  }
  out.entities.sort((a,b)=>a.distance-b.distance);
  if(req.target) {
    const target=lookup(table,req.target,0x360);
    if(!target)throw new Error('target handle expired');
    const path=scratch+0x200,record=scratch+0x300;
    gp(path).writeByteArray(new Uint8Array(64));
    const built=callGuest(cpu,0x866d5c0,[path,req.target,0,0],null,null);
    out.target={id:hx(req.target),path:hexBytes(path,28),built};
    out.target.operation=callGuest(cpu,0x84d8790,[target],null,null).ret;
    if(req.resolve) {
      const targetControllerId=g32(target+0x14);
      const array=scratch+0x500,entry=scratch+0x520;
      gp(array).writeU64(entry);gp(array+8).writeU64(1);gp(entry).writeU64(targetControllerId);
      gp(record).writeByteArray(new Uint8Array(80));
      for(const o of [0,4,8,16])gp(record+o).writeS32(-1);
      // The caller 0x80D4F00 sets the original power at +4 before resolution.
      gp(record+4).writeU32(req.power);
      out.target.resolve=callGuest(cpu,0x80d5210,[array,player,req.power,1,record],null,null);
      out.target.resolved=hexBytes(record,20);
    }
    if(req.powerEnum!==null) {
      const power=callGuest(cpu,0x84eaf50,[req.powerEnum],null,null).ret;
      out.target.power=power;
    }
  }
  return out;
}
"""


def build_js(context: int, read_ui: bool = False) -> str:
    js = bridge.JS.replace("__CONTEXT__", hex(context)).replace("__FRAME__", "0x804f9c0")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "0x19")
    if read_ui:
        js = js.replace("const FRAME = 0x804f9c0;", "const FRAME = 0x80fc310;")
        js = js.replace("const HOOK_EVENT = 0x19;", "const HOOK_EVENT = null;")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {", "if (req.mode === 'scene') { result = scene(cpu, req); } else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=0x150030E60)
    ap.add_argument("--radius", type=float, default=80)
    ap.add_argument("--defs", action="store_true")
    ap.add_argument("--read-ui", action="store_true", help="allow read-only inspection while UI consumes world input")
    ap.add_argument("--target", type=lambda s: int(s, 0))
    ap.add_argument("--screen", help="engine pixel x,y for native ray picking")
    ap.add_argument("--mask", type=lambda s:int(s,0), default=0x45)
    ap.add_argument("--power-enum", type=lambda s: int(s, 0))
    ap.add_argument("--resolve", action="store_true", help="unvalidated action-selection diagnostic; no action submission")
    ap.add_argument("--power", type=lambda s: int(s, 0), default=0x777C)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.resolve and args.target is None:
        ap.error("--resolve needs an explicit --target")
    if args.read_ui and args.resolve:
        ap.error("--read-ui is read-only")
    build = assert_installed()
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe" for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is no longer running")
    session = device.attach(args.pid)
    try:
        script = session.create_script(build_js(args.context, args.read_ui))
        script.on("message", lambda m, d: print(m, flush=True) if m.get("type") == "error" else None)
        script.load()
        script.exports_sync.arm({"mode": "scene", "radius": args.radius, "defs": args.defs,
            "target": args.target, "powerEnum": args.power_enum, "resolve":args.resolve,
            "power": args.power, "mask":args.mask,
            "screen":[int(v) for v in args.screen.split(",")] if args.screen else None})
        deadline = time.monotonic() + 10
        data = {}
        while time.monotonic() < deadline:
            data = script.exports_sync.result()
            if data.get("result"):
                break
            time.sleep(0.1)
    finally:
        session.detach()
    data["build"] = build
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    result = data.get("result") or {}
    print(json.dumps({k:v for k,v in result.items() if k != "entities"}, indent=2))
    for ent in result.get("entities", []):
        print(ent["id"], "type", ent["type"], "sno", ent["sno"], "distance", round(ent["distance"],2), "screen", ent["screen"])
    if not result.get("ok"):
        raise SystemExit("scene probe did not complete")


if __name__ == "__main__":
    main()
