"""Scan interactable world entities and optionally submit the native operate record.

The action record layout is the one observed from a natural native A press on an
NPC/gizmo (see windows/docs/HANDOFF-20261104-CURRENT.md):

  +0  controller handle of the target (entity + 0x14)
  +4  operate power from 0x84D8790(entity)
  +8  same power
  +C  0
  +10 -1
  +14 type=1 path built by 0x866D5C0(path, actor_handle, 0, 0)

`0x80CBA30(player_object, record, 1, 1)` is the same submit entry the natural
press reaches.  Modes:

  --scan                     list entities, screen projection and operate power
  --target <handle>          build the record and report it; submits only with --submit

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
function scanScene(cpu, req) {
  const s=frameScene(cpu);
  const pos=xyz(s.ent+0x60), n=g32(s.table+0x100), shift=g32(s.table+0x168), buckets=g64(s.table+0x120);
  if(n>65536 || shift>16)throw new Error('invalid table');
  const sp=cpu.add(248).readU64().toNumber(), scratch=sp-0x20000;
  const out={ok:true,ctx:hx(s.ctx),player:hx(s.player),actor:hx(s.actor),entity:hx(s.ent),
    controller:hx(s.controller),pos,place:g32(s.ent+0xa0),entities:[]};
  for(let i=0;i<n;i++) {
    const bucket=g64(buckets+(i>>shift)*8); if(!bucket)continue;
    const e=bucket+(i&((1<<shift)-1))*0x360, id=g32(e);
    if(!id || id===0xffffffff || (id&0xffff)!==i)continue;
    const p=xyz(e+0x60),distance=Math.hypot(...p.map((v,k)=>v-pos[k]));
    if(!Number.isFinite(distance) || distance>req.radius)continue;
    const type=g32(e+0x14c),sno=g32(e+0x18),ctrl=g32(e+0x14);
    for(let k=0;k<3;k++)gp(scratch+k*4).writeFloat(p[k]);
    gp(scratch+12).writeU32(g32(e+0xa0));
    const proj=callGuest(cpu,0x826ca70,[scratch,scratch+0x100,0xffffffff],null,null);
    const screen=[gp(scratch+0x100).readFloat(),gp(scratch+0x104).readFloat()];
    for(let k=0;k<3;k++)gp(scratch+k*4).writeFloat(p[k]+(k===2?req.top:0));
    callGuest(cpu,0x826ca70,[scratch,scratch+0x100,0xffffffff],null,null);
    const head=[gp(scratch+0x100).readFloat(),gp(scratch+0x104).readFloat()];
    const cap=callGuest(cpu,0x84d8790,[e],null,null);
    const kind=callGuest(cpu,0x84d7db0,[e],null,null).ret;
    out.entities.push({id:hx(id),entry:hx(e),type,sno,ctrl:hx(ctrl),pos:p,distance,
      screen,head,cap:cap.ret|0,kind:kind|0,projOk:proj.ret|0,place:g32(e+0xa0),
      flags:gp(e+0x160).readU16()});
  }
  out.entities.sort((a,b)=>a.distance-b.distance);
  return out;
}
function pickScene(cpu, req) {
  const s=frameScene(cpu);
  const sp=cpu.add(248).readU64().toNumber(), scratch=sp-0x20000;
  gp(scratch+0x100).writeByteArray(new Uint8Array(256));
  gp(scratch).writeS32(req.screen[0]); gp(scratch+4).writeS32(req.screen[1]);
  const rayCall=callGuest(cpu,0x826c7b0,[scratch,scratch+0x180,0xffffffff],null,null);
  const ray=Array.from({length:7},(_,i)=>gp(scratch+0x180+i*4).readFloat());
  const originOffset=xyz(g64(0x914f918));
  for(let k=0;k<3;k++)ray[k]+=originOffset[k];
  const n=Math.hypot(ray[3],ray[4],ray[5]);
  if(!ray.every(Number.isFinite)||!(n>1e-6)||!(ray[6]>0))throw new Error('invalid camera ray');
  const dir=[ray[3]/n,ray[4]/n,ray[5]/n];
  for(let k=0;k<3;k++)ray[3+k]=dir[k];
  for(let k=0;k<7;k++)gp(scratch+0x180+k*4).writeFloat(ray[k]);
  gp(scratch+0x200).writeByteArray(new Uint8Array(0x40));
  const terrain=callGuest(cpu,0x813e6a0,[scratch,scratch+0x200,0x45,0xffffffff,
                         scratch+0x220,scratch+0x224,scratch+0x228,scratch+0x22c],null,null);
  const terrainDepth=terrain.ret?gp(scratch+0x22c).readFloat():null;
  const depthLimit=Math.min(ray[6],Number.isFinite(terrainDepth)&&terrainDepth>=0?terrainDepth:ray[6])+0.05;
  const pos=xyz(s.ent+0x60), table=s.table;
  const count=g32(table+0x100), shift=g32(table+0x168), buckets=g64(table+0x120);
  if(count>65536||shift>16)throw new Error('invalid entity table');
  const out={ok:true,ctx:hx(s.ctx),player:hx(s.player),actor:hx(s.actor),entity:hx(s.ent),
    hp:{},pos,screen:req.screen,rayCall:{ret:rayCall.ret,returned:rayCall.returned},
    ray,dir,eye:ray.slice(0,3),terrainDepth,depthLimit,candidates:[],cylinderHits:[],assistCandidates:[]};
  for (const [name,id] of [['cur',0xFFFFF073],['a',0xFFFFF072],['b',0xFFFFF074],['c',0xFFFFF075]]) {
    const hr=callGuest(cpu,0x8474B30,[s.ent,id],null,null);
    out.hp[name]=hr.returned?hr.f0:null;
  }
  for(let i=0;i<count;i++) {
    const bucket=g64(buckets+(i>>shift)*8); if(!bucket)continue;
    const e=bucket+(i&((1<<shift)-1))*0x360, id=g32(e);
    if(!id || id===0xffffffff || (id&0xffff)!==i || id===s.actor)continue;
    const p=xyz(e+0x60),distance=Math.hypot(p[0]-pos[0],p[1]-pos[1]);
    if(!Number.isFinite(distance) || distance>req.radius)continue;
    const cap=callGuest(cpu,0x84d8790,[e],null,null).ret|0;
    const cylinder=Array.from({length:5},(_,j)=>gp(e+0x80+j*4).readFloat());
    if(g32(e+0x14c)===1)for(let k=0;k<3;k++)cylinder[k]=p[k];
    const controller=g32(e+0x14);
    if(g32(e+0xa0)===g32(s.ent+0xa0)&&controller!==0xffffffff&&
       cylinder.every(Number.isFinite)&&cylinder[3]>0&&cylinder[4]>0){
      for(let k=0;k<5;k++)gp(scratch+0x260+k*4).writeFloat(cylinder[k]);
      const test=callGuest(cpu,0x8a35250,[scratch+0x180,scratch+0x260,scratch+0x240],null,null);
      const depth=test.ret?gp(scratch+0x240).readFloat():null;
      if(test.ret&&Number.isFinite(depth)&&depth>=0&&depth<depthLimit)
        out.cylinderHits.push({id:hx(id),sno:g32(e+0x18),cap,depth,cylinder});
    }
    if(g32(e+0xa0)===g32(s.ent+0xa0)&&controller!==0xffffffff&&cap>0&&cap!==0x45ccf){
      // Mirror the current production assist projection, including its known
      // use of radius as height.  This is a preflight superset, not a fix for it.
      const height=Number.isFinite(cylinder[4])&&cylinder[4]>0&&cylinder[4]<4?cylinder[4]:0;
      const ends=[];
      for(const h of [0,height]){
        for(let k=0;k<3;k++)gp(scratch+12+k*4).writeFloat(p[k]+(k===2?h:0));
        gp(scratch+24).writeU32(g32(e+0xa0));
        callGuest(cpu,0x826ca70,[scratch+12,scratch+0x100,0xffffffff],null,null);
        const xy=[gp(scratch+0x100).readFloat(),gp(scratch+0x104).readFloat()];
        if(!xy.every(Number.isFinite))throw new Error('invalid assist projection');
        ends.push(xy);
      }
      const y0=Math.min(ends[0][1],ends[1][1]),y1=Math.max(ends[0][1],ends[1][1]);
      const cy=Math.max(y0,Math.min(y1,req.screen[1]));
      const screenDistance=Math.hypot(req.screen[0]-(ends[0][0]+ends[1][0])*0.5,req.screen[1]-cy);
      if(screenDistance<=14)out.assistCandidates.push({id:hx(id),sno:g32(e+0x18),cap,distance,screenDistance,ends});
    }
    const v=[p[0]-ray[0],p[1]-ray[1],p[2]-ray[2]];
    const t=v[0]*dir[0]+v[1]*dir[1]+v[2]*dir[2];
    const closest=[ray[0]+dir[0]*t,ray[1]+dir[1]*t,ray[2]+dir[2]*t];
    const lateral=Math.hypot(...closest.map((c,k)=>c-p[k]));
    // projected segment: base..base+height along each axis plus a small spread
    let best=1e9,bestAt=null;
    for(let k=0;k<=4;k++) {
      const q=[p[0],p[1],p[2]+req.height*k/4];
      for(let j=0;j<3;j++)gp(scratch+12+j*4).writeFloat(q[j]);
      gp(scratch+24).writeU32(g32(e+0xa0));
      callGuest(cpu,0x826ca70,[scratch+12,scratch+0x100,0xffffffff],null,null);
      const sx=gp(scratch+0x100).readFloat(),sy=gp(scratch+0x104).readFloat();
      const d=Math.hypot(sx-req.screen[0],sy-req.screen[1]);
      if(d<best){best=d;bestAt=[sx,sy];}
    }
    out.candidates.push({id:hx(id),type:g32(e+0x14c),sno:g32(e+0x18),cap,
      distance,t,lateral,screen:bestAt,screenDistance:best,
      place:g32(e+0xa0)});
  }
  out.candidates.sort((a,b)=>a.screenDistance-b.screenDistance);
  out.cylinderHits.sort((a,b)=>a.depth-b.depth);
  out.assistCandidates.sort((a,b)=>a.screenDistance-b.screenDistance);
  return out;
}
function skillScene(cpu, req) {
  const s=frameScene(cpu);
  const out={player:hx(s.player), slots:[]};
  for(let slot=0; slot<6; slot++){
    const r=callGuest(cpu,0x8525ED0,[s.player,slot],null,null);
    let power=null;
    if(r.returned && r.ret) { try { power=gm.add(r.ret).readU32(); } catch(e) { power='err'; } }
    out.slots.push({slot, returned:r.returned, ptr:r.ret, power});
  }
  out.ok=out.slots.every(s=>s.returned && s.ptr && typeof s.power==='number');
  return out;
}
function cooldownScene(cpu, req) {
  const s=frameScene(cpu);
  const out={ok:true,ctx:hx(s.ctx),player:hx(s.player),actor:hx(s.actor),slots:[]};
  for(let slot=0;slot<6;slot++){
    const r=callGuest(cpu,0x8525ED0,[s.player,slot],null,null);
    let power=null;
    if(r.returned && r.ret){try{power=gm.add(r.ret).readU32();}catch(e){power=null;}}
    const row={slot,power,remaining:null,total:null,remaining_ok:false,total_ok:false};
    if(typeof power==='number' && power && power!==0xffffffff){
      const total=callGuest(cpu,0x89bceb0,[power],null,null);
      row.total=total.returned?total.f0:null; row.total_ok=!!(total.returned||total.returned===0);
      const remaining=callGuest(cpu,0x89c2080,[s.actor,power],null,null);
      row.remaining=remaining.returned?remaining.f0:null; row.remaining_ok=!!(remaining.returned||remaining.returned===0);
    }
    out.slots.push(row);
  }
  out.ok=out.slots.every(s=>s.power===null||(s.total_ok&&s.remaining_ok));
  return out;
}
function cooldownOneScene(cpu, req) {
  const s=frameScene(cpu);
  const power=req.power;
  const total=callGuest(cpu,0x89bceb0,[power],null,null);
  const remaining=callGuest(cpu,0x89c2080,[s.actor,power],null,null);
  return {ok:true,player:hx(s.player),actor:hx(s.actor),power,total:total.f0,remaining:remaining.f0,
          total_returned:!!total.returned,remaining_returned:!!remaining.returned};
}
function cooldownTotalScene(cpu, req) {
  const s=frameScene(cpu);
  const out={ok:true,player:hx(s.player),actor:hx(s.actor),slots:[]};
  for(let slot=0;slot<6;slot++){
    const r=callGuest(cpu,0x8525ED0,[s.player,slot],null,null);
    let power=null;
    if(r.returned && r.ret){try{power=gm.add(r.ret).readU32();}catch(e){power=null;}}
    const row={slot,power,total:null,returned:false};
    if(typeof power==='number' && power && power!==0xffffffff){
      const t=callGuest(cpu,0x89bceb0,[power],null,null);
      row.total=t.f0; row.returned=!!t.returned;
    }
    out.slots.push(row);
  }
  return out;
}
function cooldownRemainingScene(cpu, req) {
  const s=frameScene(cpu);
  const out={ok:true,player:hx(s.player),actor:hx(s.actor),slots:[]};
  for(let slot=0;slot<6;slot++){
    const r=callGuest(cpu,0x8525ED0,[s.player,slot],null,null);
    let power=null;
    if(r.returned && r.ret){try{power=gm.add(r.ret).readU32();}catch(e){power=null;}}
    const row={slot,power,remaining:null,returned:false};
    if(typeof power==='number' && power && power!==0xffffffff){
      const t=callGuest(cpu,0x89c2080,[s.actor,power],null,null);
      row.remaining=t.f0; row.returned=!!t.returned;
    }
    out.slots.push(row);
  }
  return out;
}
function attributesScene(cpu, req) {
  const s=frameScene(cpu);
  const out={ok:true,player:hx(s.player),entity:hx(s.ent),start:req.start,count:req.count,values:[]};
  for(let i=0;i<req.count;i++){
    const id=(req.start+i)>>>0;
    const r=callGuest(cpu,0x8474B30,[s.ent,id],null,null);
    out.values.push({id:'0x'+id.toString(16),value:r.f0,returned:!!r.returned});
  }
  return out;
}
function playerStateScene(cpu, req) {
  const s=frameScene(cpu);
  const hp=callGuest(cpu,0x8474B30,[s.ent,0xFFFFF073],null,null);
  return {ok:!!hp.returned,ctx:hx(s.ctx),player:hx(s.player),actor:hx(s.actor),entity:hx(s.ent),
          pos:xyz(s.ent+0x60),place:g32(s.ent+0xa0),hp:{cur:hp.f0}};
}
function hpScene(cpu, req) {
  const e=req.entity;
  const actor=g32(e), sno=g32(e+0x18);
  if(req.actor!==undefined && actor!==req.actor)
    return {ok:false,entity:hx(e),actor:hx(actor),sno,error:'entity identity changed'};
  const hcur=callGuest(cpu,0x8474B30,[e,0xFFFFF073],null,null);
  const hmax=callGuest(cpu,0x8474B30,[e,0xFFFFF074],null,null);
  return {ok:hcur.returned&&hmax.returned,entity:hx(e),actor:hx(actor),sno,
    hp:{cur:hcur.returned?hcur.f0:null,max:hmax.returned?hmax.f0:null}};
}
function interactScene(cpu, req) {
  const s=frameScene(cpu);
  const e=lookup(s.table,req.target,0x360);
  if(!e)throw new Error('target handle expired');
  const actor=g32(e), ctrl=g32(e+0x14), type=g32(e+0x14c), sno=g32(e+0x18);
  const pos=xyz(e+0x60), playerPos=xyz(s.ent+0x60);
  const cap=callGuest(cpu,0x84d8790,[e],null,null);
  const power=cap.ret|0;
  const sp=cpu.add(248).readU64().toNumber(), scratch=sp-0x20000;
  const rec=scratch, path=rec+0x14;
  gp(rec).writeByteArray(new Uint8Array(0x60));
  gp(rec).writeU32(ctrl); gp(rec+4).writeU32(power); gp(rec+8).writeU32(power);
  gp(rec+0xc).writeU32(0); gp(rec+0x10).writeU32(0xffffffff);
  const built=callGuest(cpu,0x866d5c0,[path,actor,0,0],null,null);
  const out={ok:true,ctx:hx(s.ctx),player:hx(s.player),playerEntity:hx(s.ent),
    target:hx(actor),entity:hx(e),ctrl:hx(ctrl),type,sno,power,pos,playerPos,
    distance:Math.hypot(...pos.map((v,k)=>v-playerPos[k])),
    path:hexBytes(path,28),built:{ret:built.ret,returned:built.returned,pc:built.pc},
    record:hexBytes(rec,0x30),submit:null};
  const hcur=callGuest(cpu,0x8474B30,[e,0xFFFFF073],null,null);
  const hmax=callGuest(cpu,0x8474B30,[e,0xFFFFF074],null,null);
  out.hp={cur:hcur.returned?hcur.f0:null,max:hmax.returned?hmax.f0:null};
  if(req.submit) {
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
                      "if (req.mode === 'scan') { result = scanScene(cpu, req); } "
                      "else if (req.mode === 'pick') { result = pickScene(cpu, req); } "
                      "else if (req.mode === 'interact') { result = interactScene(cpu, req); } "
                      "else if (req.mode === 'hp') { result = hpScene(cpu, req); } "
                      "else if (req.mode === 'player_state') { result = playerStateScene(cpu, req); } "
                      "else if (req.mode === 'attributes') { result = attributesScene(cpu, req); } "
                      "else if (req.mode === 'cooldown') { result = cooldownScene(cpu, req); } "
                      "else if (req.mode === 'cooldown_total') { result = cooldownTotalScene(cpu, req); } "
                      "else if (req.mode === 'cooldown_one') { result = cooldownOneScene(cpu, req); } "
                      "else if (req.mode === 'cooldown_remaining') { result = cooldownRemainingScene(cpu, req); } "
                      "else if (req.mode === 'skill') { result = skillScene(cpu, req); } "
                      "else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=0x150030E60)
    ap.add_argument("--radius", type=float, default=60)
    ap.add_argument("--top", type=float, default=1.8, help="head offset for the screen segment")
    ap.add_argument("--target", type=lambda s: int(s, 0))
    ap.add_argument("--entity", type=lambda s: int(s, 0), help="raw entity pointer for a read-only HP read")
    ap.add_argument("--skill", action="store_true", help="read the six hero skill loadout powers")
    ap.add_argument("--cooldown", action="store_true", help="read remaining/total cooldown for the six hero skill slots")
    ap.add_argument("--cooldown-total", action="store_true", help="read total cooldown for the six hero skill slots")
    ap.add_argument("--cooldown-remaining", action="store_true", help="read remaining cooldown for the six hero skill slots")
    ap.add_argument("--cooldown-one", type=lambda s: int(s, 0), help="read total/remaining cooldown for one power SNO")
    ap.add_argument("--attr-start", type=lambda s: int(s, 0), help="attribute id scan start")
    ap.add_argument("--attr-count", type=int, default=64, help="attribute id scan count")
    ap.add_argument("--click", help="engine pixel x,y to resolve the entity under the cursor")
    ap.add_argument("--height", type=float, default=2.0, help="world height sampled for the screen test")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.submit and args.target is None:
        ap.error("--submit needs --target")
    build = assert_installed()
    from session_driver import _process_identity
    identity = _process_identity(args.pid)
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe" for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is no longer running")
    session = device.attach(args.pid)
    try:
        script = session.create_script(build_js(args.context))
        script.on("message", lambda m, d: print(m, flush=True) if m.get("type") == "error" else None)
        script.load()
        if args.click:
            req = {"mode": "pick", "radius": args.radius, "height": args.height,
                   "screen": [int(v) for v in args.click.split(",")]}
        elif args.skill:
            req = {"mode": "skill"}
        elif args.cooldown:
            req = {"mode": "cooldown"}
        elif args.cooldown_total:
            req = {"mode": "cooldown_total"}
        elif args.cooldown_remaining:
            req = {"mode": "cooldown_remaining"}
        elif args.cooldown_one is not None:
            req = {"mode": "cooldown_one", "power": args.cooldown_one}
        elif args.attr_start is not None:
            req = {"mode": "attributes", "start": args.attr_start, "count": args.attr_count}
        elif args.entity is not None:
            req = {"mode": "hp", "entity": args.entity}
        elif args.target is None:
            req = {"mode": "scan", "radius": args.radius, "top": args.top}
        else:
            req = {"mode": "interact", "target": args.target, "submit": args.submit}
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
    data["identity"] = identity
    data["req"] = req
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    result = data.get("result") or {}
    print(json.dumps({k: v for k, v in result.items() if k not in ("entities", "candidates")}, indent=2))
    for ent in result.get("entities", []):
        print(f'{ent["id"]} type {ent["type"]:>2} sno {ent["sno"]:>7} cap {ent["cap"]:>6} '
              f'kind {ent["kind"]:>3} d {ent["distance"]:6.2f} screen '
              f'({ent["screen"][0]:7.1f},{ent["screen"][1]:7.1f}) head '
              f'({ent["head"][0]:7.1f},{ent["head"][1]:7.1f})')
    for cand in result.get("candidates", []):
        print(f'{cand["id"]} type {cand["type"]:>2} sno {cand["sno"]:>7} cap {cand["cap"]:>6} '
              f'd {cand["distance"]:6.2f} t {cand["t"]:6.2f} lat {cand["lateral"]:5.2f} '
              f'px {cand["screenDistance"]:6.1f} at ({cand["screen"][0]:7.1f},{cand["screen"][1]:7.1f})')
    if not result.get("ok"):
        raise SystemExit("probe did not complete")


if __name__ == "__main__":
    main()
