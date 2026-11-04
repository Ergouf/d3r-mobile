"""Submit the game's own "attack at point" record and report the result.

The record is the one a natural A press builds when nothing is interactable:
  +0  controller 0xFFFFFFFF, +4/+8 power 0x45CCF, +0xC 0, +0x10 -1,
  +0x14 a type-2 position path built by 0x866D580(path, world_pos).
0x80CBA30(player, record, 1, 1) is the same submit entry the native press reaches.
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
function frameScene(cpu) {
  const player=callGuest(cpu,0x8525360,[0],null,null).ret;
  if(!player) throw new Error('local player not active');
  const actor=g32(player+4), ctx=liveContext(cpu,SLOT);
  const table=g64(g64(g64(g64(ctx))+0x198));
  const ent=lookup(table,actor,0x360);
  if(!ent)throw new Error('local player handle expired');
  const world=g64(g64(0x914f840)+16), ctrlId=g32(player+8);
  const controller=lookup(g64(world+0xa98),ctrlId,0x410);
  if(!controller || g32(controller+8)!==actor)throw new Error('controller mismatch');
  return {player,actor,ctx,table,ent,world,controller,ctrlId};
}
function attackScene(cpu, req) {
  const s=frameScene(cpu);
  const sp=cpu.add(248).readU64().toNumber(), scratch=sp-0x20000;
  const rec=scratch, path=rec+0x14, pos=scratch+0x100;
  gp(rec).writeByteArray(new Uint8Array(0x80));
  gp(rec).writeU32(0xffffffff); gp(rec+4).writeU32(0x45ccf); gp(rec+8).writeU32(0x45ccf);
  gp(rec+0xc).writeU32(0); gp(rec+0x10).writeU32(0xffffffff);
  for(let k=0;k<3;k++) gp(pos+k*4).writeFloat(req.pos[k]);
  gp(pos+12).writeU32(req.place);
  const built=callGuest(cpu,0x866d580,[path,pos],null,null);
  const out={ok:true,ctx:hx(s.ctx),player:hx(s.player),actor:hx(s.actor),entity:hx(s.ent),
    playerPos:xyz(s.ent+0x60),place:g32(s.ent+0xa0),target:req.pos,targetPlace:req.place,
    path:hexBytes(path,28),built:{ret:built.ret,returned:built.returned,pc:built.pc},submit:null};
  if(req.submit) {
    if(!built.returned || hexBytes(path,8)!=='02000000ffffffff') {
      out.submit='skipped (path build failed)';
      return out;
    }
    const r=callGuest(cpu,0x80cba30,[s.player,rec,1,1],null,null);
    out.submit={ret:r.ret|0,returned:r.returned,pc:r.pc,steps:r.steps};
  }
  return out;
}
"""


def build_js(context: int) -> str:
    js = bridge.JS.replace("__CONTEXT__", hex(context)).replace("__FRAME__", "0x804f9c0")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "0x19")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
                      "if (req.mode === 'attack') { result = attackScene(cpu, req); } "
                      "else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=0x150030E60)
    ap.add_argument("--pos", required=True, help="world x,y,z of the attack point")
    ap.add_argument("--place", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe"
               for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is no longer running")
    session = device.attach(args.pid)
    try:
        script = session.create_script(build_js(args.context))
        script.on("message", lambda m, d: print(m, flush=True) if m.get("type") == "error" else None)
        script.load()
        req = {"mode": "attack", "pos": [float(v) for v in args.pos.split(",")],
               "place": args.place, "submit": args.submit}
        script.exports_sync.arm(req)
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
    data["req"] = req
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    print(json.dumps(data.get("result") or {}, indent=2))


if __name__ == "__main__":
    main()
