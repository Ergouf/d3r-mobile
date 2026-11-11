"""Inspect native spatial-index ray hits on the game thread, without input.

Uses the engine's published collision spheres and ray/sphere test. The query
is deliberately separate from action submission; broad-phase hits are evidence
about bounds, not proof that a model mesh or UI control was clicked.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_click_interact as scene
from version import assert_installed

EXTENSION = r"""
function mapController(map,key) {
  let h=0x811c9dc5;
  for(let j=0;j<4;j++)h=Math.imul(h^((key>>>(j*8))&255),0x1000193)>>>0;
  const mask=g32(map),buckets=g64(map+0x10);
  for(let node=g64(buckets+(h&mask)*8),n=0;node && n++<1024;node=g64(node)) {
    if(g64(node+8)===key)return g32(node+0x10);
  }
  return null;
}
function enginePick(cpu,req) {
  const s=frameScene(cpu),sp=cpu.add(248).readU64().toNumber(),scratch=sp-0x20000;
  const pixel=scratch,ray=scratch+0x40,hit=scratch+0x80,terrain=scratch+0x100;
  gp(pixel).writeS32(req.screen[0]);gp(pixel+4).writeS32(req.screen[1]);
  callGuest(cpu,0x826c7b0,[pixel,ray,0xffffffff],null,null);
  const offset=xyz(g64(0x914f918));
  for(let k=0;k<3;k++)gp(ray+k*4).writeFloat(gp(ray+k*4).readFloat()+offset[k]);
  const terrainCall=callGuest(cpu,0x813e6a0,[pixel,terrain,0x45,0xffffffff,terrain+0x20,
    terrain+0x24,terrain+0x28,terrain+0x2c],null,null);
  const out={ok:true,actor:hx(s.actor),pos:xyz(s.ent+0x60),screen:req.screen,
    ray:Array.from({length:7},(_,k)=>gp(ray+k*4).readFloat()),offset,
    terrain:{ret:terrainCall.ret,position:xyz(terrain),distance:gp(terrain+0x2c).readFloat()},trees:[]};
  const index=g64(s.world+0xb30),map=g64(index+0x10),ctrlTable=g64(s.world+0xa98);
  for(let k=0;k<2;k++) {
    const tree=g64(index+k*8);
    callGuest(cpu,0x8a2ad50,[tree],null,null);
    const count=g32(tree+0x68),bounds=g64(tree+0x60),keys=g64(tree+0x98);
    if(count>100000)throw new Error('invalid spatial index');
    const t={tree:hx(tree),count,bounds:hx(bounds),hits:[]};
    for(let i=0;i<count;i++) {
      const sphere=bounds+i*16,key=g64(keys+i*8);
      const cid=mapController(map,key),ctrl=cid===null?null:lookup(ctrlTable,cid,0x410);
      if(!ctrl)continue;
      const actor=g32(ctrl+8),entity=lookup(s.table,actor,0x360);
      const r=callGuest(cpu,0x8a349a0,[ray,sphere,hit,0],null,null);
      if(!r.ret && actor!==req.target)continue;
      const sphereDistance=gp(hit).readFloat();
      const cylinder=callGuest(cpu,0x8a35250,[ray,ctrl+0x50,hit],null,null);
      const cyl={hit:cylinder.ret,distance:gp(hit).readFloat(),bounds:
          Array.from({length:5},(_,i)=>gp(ctrl+0x50+i*4).readFloat())};
      let actorCylinder=null;
      if(entity) {
        const ac=callGuest(cpu,0x8a35250,[ray,entity+0x80,hit],null,null);
        actorCylinder={hit:ac.ret,distance:gp(hit).readFloat(),bounds:
          Array.from({length:5},(_,i)=>gp(entity+0x80+i*4).readFloat())};
      }
      t.hits.push({key,controller:hx(cid),actor:hx(actor),entity:entity?hx(entity):null,
        sno:entity?g32(entity+0x18):null,type:g32(ctrl+0x18),hit:r.ret,
        distance:sphereDistance,sphere:xyz(sphere).concat(gp(sphere+12).readFloat()),
        cylinder:cyl,actorCylinder,
        controllerBytes:hexBytes(ctrl,0x120)});
    }
    t.hits.sort((a,b)=>a.distance-b.distance);out.trees.push(t);
  }
  return out;
}
"""


def build_js() -> str:
    js = scene.build_js(0x150030E60)
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'scan') {",
                      "if (req.mode === 'engine-pick') { result = enginePick(cpu,req); } else if (req.mode === 'scan') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--screen", required=True)
    ap.add_argument("--target", type=lambda s: int(s, 0))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe" for p in device.enumerate_processes()):
        raise SystemExit("game is no longer running")
    session = device.attach(args.pid)
    try:
        script = session.create_script(build_js())
        script.on("message", lambda m,d: print(m,flush=True) if m.get("type")=="error" else None)
        script.load()
        script.exports_sync.arm({"mode":"engine-pick","screen":[int(v) for v in args.screen.split(",")],"target":args.target})
        data = {}
        deadline = time.monotonic() + 12
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
    for tree in result.get("trees", []):
        for hit in tree["hits"]:
            hit.pop("controllerBytes", None)
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit("engine pick did not complete")


if __name__ == "__main__":
    main()
