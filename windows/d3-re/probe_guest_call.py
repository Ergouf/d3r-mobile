#!/usr/bin/env python3
"""Call guest functions on the game thread from inside a per-frame hook.

The runtime's own bridge does not pass x8/s0 and does not select a thread, so this probe takes
the live ``CPU*`` that the engine's per-frame HID update (``0x80FC310``) receives and runs guest
code on that thread through the runtime dispatch table (``resolveGuest``).

Contract of one call:

  * the target's dispatch entry must resolve before anything is written; the entry address is
    reported,
  * x0..x7, x8 and s0 come from the request, x30 = 0 is the return sentinel,
  * the call only counts as returned when the guest pc comes back as 0 afterwards,
  * the whole mutable CPU state is saved and restored: x0..x30, sp, pc, nzcv, fpcr/fpsr,
    v0..v31, the exclusive monitor and the poll flag.

Modes:

  --target <guest> --arg ... [--x8 sp-0x4000] [--dump-len N]   one call
  --move dx,dy,dz [--speed S] [--w2 N] [--no-submit]           read the entity position with
      0x847CEA0 (all four words), build a type=2 path with 0x866D580, preflight the actor-id
      table, submit with 0x8828460, read the position again **through the entity**

Nothing runs unless a request is armed.  Buffers live on the guest stack below SP, the same
convention ``call_guest.py`` uses.

Usage:
  python windows/d3-re/probe_guest_call.py --pid <pid> --target 0x847cea0 --arg 0x15cb2ac00 --x8 sp-0x4000
  python windows/d3-re/probe_guest_call.py --pid <pid> --move 3,0,0 --actor 0x78040048 --context 0x150030e60
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

FRAME = 0x80FC310
ENTITY_POS = 0x847CEA0
PATH_FROM_POS = 0x866D580
MOVE_SUBMIT = 0x8828460
HOLDER = 0x914F8D0

JS = js_consts() + f"""
const FRAME = __FRAME__;
const AFTER = __AFTER__;
const HOOK_EVENT = __EVENT__;
const ENTITY_POS = 0x{ENTITY_POS:x}, PATH_FROM_POS = 0x{PATH_FROM_POS:x}, MOVE_SUBMIT = 0x{MOVE_SUBMIT:x};
const HOLDER = 0x{HOLDER:x};
const V0 = 280, PC = 256, NZCV = 264, FPCR = 792, FPSR = 796;
const EXCL = 816, POLL = 896, CPU_SIZE = 904, STACK_SIZE = 0x40000;
const CONTEXT = __CONTEXT__;

function gp(a) {{ return gm.add(typeof a === 'string' ? parseInt(a, 16) : a); }}
function hexBytes(a, n) {{
  try {{ return Array.from(new Uint8Array(gp(a).readByteArray(n)), b => b.toString(16).padStart(2, '0')).join(''); }}
  catch (e) {{ return 'err:' + e.message; }}
}}
function mapped(a) {{
  const r = Process.findRangeByAddress(gp(a));
  return r ? {{ base: r.base.toString(), size: r.size, protection: r.protection }} : null;
}}
function u32(hex, i) {{
  const s = hex.substr(i * 8, 8);
  return parseInt(s.substr(6, 2) + s.substr(4, 2) + s.substr(2, 2) + s.substr(0, 2), 16) >>> 0;
}}
function f32(hex, i) {{
  const b = [];
  for (let k = 0; k < 4; k++) b.push(parseInt(hex.substr(i * 8 + k * 2, 2), 16));
  return new DataView(new Uint8Array(b).buffer).getFloat32(0, true);
}}

/* same bucket lookup the engine uses: index = handle & 0xffff */
function entityFromHandle(handle) {{
  if (CONTEXT === null) return null;
  try {{
    const a = gp(CONTEXT).readU64().toNumber();
    const b = gp(a).readU64().toNumber();
    const c = gp(b + 0x198).readU64().toNumber();
    const table = gp(c).readU64().toNumber();
    const count = gp(table + 0x100).readU32();
    const shift = gp(table + 0x168).readU32();
    const buckets = gp(table + 0x120).readU64().toNumber();
    const index = handle & 0xffff;
    if (index >= count) return null;
    const base = gp(buckets + (index >> shift) * 8).readU64().toNumber();
    const entry = base + (index & ((1 << shift) - 1)) * 0x360;
    return gp(entry).readU32() === handle ? entry : null;
  }} catch (e) {{ return null; }}
}}

/* the TLS slot this game's entity lookups use: *(*0x914F8D0) + 0xC */
function tlsSlot() {{
  try {{
    const holder = gp(HOLDER).readU64().toNumber();
    const obj = gp(holder).readU64().toNumber();
    return gp(obj + 0xC).readU32();
  }} catch (e) {{ return null; }}
}}

/* GetTlsValue on the live thread (0x9DDDF40): *(u64(TPIDRRO+0x1F8) + 0x80 + slot*8) */
function liveContext(cpu, slot) {{
  const tpidrro = cpu.add(808).readU64().toNumber();
  const block = gp(tpidrro + 0x1F8).readU64().toNumber();
  return gp(block + 0x80 + slot * 8).readU64().toNumber();
}}

/* whole mutable CPU state; mem/disp/code_lo/code_hi/rt/thread are not touched by a call */
function saveState(cpu) {{
  const s = {{ x: [], v: [], nzcv: [], excl: null }};
  for (let i = 0; i < 31; i++) s.x.push(cpu.add(i * 8).readU64());
  s.sp = cpu.add(31 * 8).readU64();
  s.pc = cpu.add(PC).readU64();
  s.nzcv = [cpu.add(NZCV).readU32(), cpu.add(NZCV + 4).readU32(),
            cpu.add(NZCV + 8).readU32(), cpu.add(NZCV + 12).readU32()];
  s.vbytes = cpu.add(V0).readByteArray(32 * 16);
  s.fpcr = cpu.add(FPCR).readU32();
  s.fpsr = cpu.add(FPSR).readU32();
  s.excl = [cpu.add(EXCL).readU64(), cpu.add(EXCL + 8).readU64(), cpu.add(EXCL + 16).readU64(),
            cpu.add(EXCL + 24).readU32(), cpu.add(EXCL + 28).readU32()];
  s.poll = cpu.add(POLL).readU32();
  return s;
}}
function restoreState(cpu, s) {{
  for (let i = 0; i < 31; i++) cpu.add(i * 8).writeU64(s.x[i]);
  cpu.add(31 * 8).writeU64(s.sp);
  cpu.add(PC).writeU64(s.pc);
  cpu.add(NZCV).writeU32(s.nzcv[0]);
  cpu.add(NZCV + 4).writeU32(s.nzcv[1]);
  cpu.add(NZCV + 8).writeU32(s.nzcv[2]);
  cpu.add(NZCV + 12).writeU32(s.nzcv[3]);
  cpu.add(V0).writeByteArray(s.vbytes);
  cpu.add(FPCR).writeU32(s.fpcr);
  cpu.add(FPSR).writeU32(s.fpsr);
  cpu.add(EXCL).writeU64(s.excl[0]);
  cpu.add(EXCL + 8).writeU64(s.excl[1]);
  cpu.add(EXCL + 16).writeU64(s.excl[2]);
  cpu.add(EXCL + 24).writeU32(s.excl[3]);
  cpu.add(EXCL + 28).writeU32(s.excl[4]);
  cpu.add(POLL).writeU32(s.poll);
}}

/* Complete one call on an isolated CPU copy; never publish partial returns. */
function callGuest(cpu, target, args, x8, s0, s1) {{
  const entry = resolveGuest(target);
  if (entry === null) throw new Error('no dispatch entry for 0x' + target.toString(16));
  for (let i = 0; i < 8; i++) cpu.add(i * 8).writePointer(ptr(i < args.length ? args[i] : 0));
  const sp = cpu.add(248).readU64().toNumber();
  for (let i = 8; i < args.length; i++) gp(sp + (i - 8) * 8).writeU64(args[i]);
  cpu.add(8 * 8).writePointer(ptr(x8 === null || x8 === undefined ? 0 : x8));
  if (s0 !== null && s0 !== undefined) {{
    const dv = new DataView(new ArrayBuffer(16));
    dv.setFloat32(0, s0, true);
    cpu.add(V0).writeByteArray(dv.buffer);
  }}
  if (s1 !== null && s1 !== undefined) cpu.add(V0 + 16).writeFloat(s1);
  cpu.add(30 * 8).writePointer(ptr(0));
  cpu.add(PC).writePointer(ptr(target));
  let steps = 0;
  const started = Date.now();
  while (cpu.add(PC).readU64().toNumber() !== 0) {{
    const next = cpu.add(PC).readU64().toNumber();
    if (++steps > 16384 || Date.now() - started > 1000)
      throw new Error('guest call did not reach return sentinel: 0x' + next.toString(16));
    const host = resolveGuest(next);
    if (host === null) throw new Error('no continuation at 0x' + next.toString(16));
    new NativeFunction(host, 'void', ['pointer', 'uint64'])(cpu, next);
  }}
  const pc = cpu.add(PC).readU64().toNumber();
  return {{ ret: cpu.add(0).readU64().toNumber(), entry: entry.toString(),
           returned: pc === 0, pc: '0x' + pc.toString(16), steps, f0: cpu.add(V0).readFloat() }};
}}

let armed = null, result = null, busy = false, frameCalls = 0, lastOut = null, stackBase = 0;
const SLOT = tlsSlot();
const runtimeModule = Process.enumerateModules().find(m => m.name.toLowerCase() === '01001b300b9be000.exe');
function stackTop() {{
  if (!stackBase) {{
    stackBase = new NativeFunction(runtimeModule.base.add(RVA.kmem_alloc), 'uint64', ['uint64', 'uint', 'uint'])(
      STACK_SIZE, 0x045C3C0B, 3).toNumber();
    if (!stackBase) throw new Error('no diagnostic guest stack');
  }}
  return stackBase + STACK_SIZE - 0x100;
}}

function runCall(cpu, req) {{
  let x8 = req.x8;
  if (req.x8Rel) {{
    const sp = cpu.add(31 * 8).readU64().toNumber();
    x8 = sp - req.x8Rel;
  }}
  const r = callGuest(cpu, req.target, req.args, x8, req.s0);
  return {{ ok: true, target: '0x' + req.target.toString(16), entry: r.entry, returned: r.returned,
           pc_after: r.pc, ret: '0x' + BigInt(r.ret).toString(16), f0: r.f0,
           buffer: x8 === null || x8 === undefined ? null :
                   {{ addr: '0x' + x8.toString(16), range: mapped(x8), hex: hexBytes(x8, req.dumpLen) }} }};
}}

function runWrite(cpu, req) {{
  const dv = new DataView(new ArrayBuffer(16));
  req.floats.forEach((v, i) => dv.setFloat32(i * 4, v, true));
  gp(req.addr).writeByteArray(dv.buffer);
  return {{ ok: true, addr: '0x' + req.addr.toString(16), hex: hexBytes(req.addr, 16) }};
}}

function runProject(cpu, req) {{
  const sp = cpu.add(248).readU64().toNumber();
  const loc = sp - 0x20000, screen = sp - 0x1f000, point = sp - 0x1e000;
  const ray = sp - 0x1d000, rect = sp - 0x1c000;
  const ent = entityFromHandle(req.actor);
  if (ent === null) throw new Error('player entity not found');
  callGuest(cpu, ENTITY_POS, [ent], loc, null);
  const original = [0,4,8].map(o => gp(loc + o).readFloat());
  for (let i=0;i<3;i++) gp(loc+i*4).writeFloat(original[i]+req.offset[i]);
  const location = [0,4,8].map(o => gp(loc+o).readFloat());
  callGuest(cpu, 0x8042940, [rect], null, null);
  const viewport = [0,4,8,12].map(o => gp(rect+o).readS32());
  const project = callGuest(cpu, 0x826ca70, [loc, screen, 0xffffffff], null, null);
  const projected = [gp(screen).readFloat(),gp(screen+4).readFloat()];
  const pixel = req.screen || projected.map(Math.round);
  gp(point).writeS32(Math.round(pixel[0])); gp(point+4).writeS32(Math.round(pixel[1]));
  callGuest(cpu, 0x826c7b0, [point, ray, 0xffffffff], null, null);
  const line = Array.from({{length:6}},(_,i)=>gp(ray+i*4).readFloat());
  const t = (location[2]-line[2])/line[5];
  const world = [0,1,2].map(i=>line[i]+line[i+3]*t);
  if (!world.every(Number.isFinite)) throw new Error('invalid world ray');
  return {{ok:true,original,location,viewport,project,projected,pixel,ray:line,world,
          error:Math.hypot(...world.map((v,i)=>v-location[i])),fourth:gp(loc+12).readU32()}};
}}

function runMove(cpu, req) {{
  const sp = cpu.add(31 * 8).readU64().toNumber();
  const pos = sp - 0x1F000, path = sp - 0x20000, cur = sp - 0x1E000;
  const out = {{ ok: true, sp: '0x' + sp.toString(16), actor: '0x' + req.actor.toString(16),
                slot: SLOT, steps: [] }};
  lastOut = out;
  const ent = req.entity || entityFromHandle(req.actor);
  out.entity = ent === null ? null : '0x' + ent.toString(16);
  if (ent === null) throw new Error('entity not found for handle');

  /* 0x847CEA0 copies entity +0x60/+0x64/+0x68/+0xA0: x, y, z and a fourth word */
  const p0 = callGuest(cpu, ENTITY_POS, [ent], cur, null);
  const before = hexBytes(cur, 16);
  out.before = {{ pos: [f32(before, 0), f32(before, 1), f32(before, 2)],
                 w_u32: u32(before, 3), w_hex: '0x' + u32(before, 3).toString(16), hex: before }};
  out.steps.push({{ step: 'entity_pos', returned: p0.returned, hex: before }});
  if (!req.goal) req.goal = [out.before.pos[0] + req.dx, out.before.pos[1] + req.dy, out.before.pos[2] + req.dz];
  out.target = req.goal;
  out.distance = Math.hypot(...out.before.pos.map((v, i) => v - req.goal[i]));
  if (req.client && out.distance <= req.radius) {{ out.arrived = true; return out; }}

  /* keep the entity's own fourth word instead of zeroing it */
  const dv = new DataView(new ArrayBuffer(16));
  dv.setFloat32(0, req.goal[0], true);
  dv.setFloat32(4, req.goal[1], true);
  dv.setFloat32(8, req.goal[2], true);
  dv.setUint32(12, out.before.w_u32, true);
  gp(pos).writeByteArray(dv.buffer);
  out.target = req.goal;
  const p1 = callGuest(cpu, PATH_FROM_POS, [path, pos], null, null);
  out.steps.push({{ step: 'path_from_pos', returned: p1.returned, hex: hexBytes(path, 0x20) }});
  const pathType = gp(path).readU32(), pathId = gp(path + 4).readU32();
  out.path = {{ type: pathType, id: pathId }};
  if (pathType !== 2 || pathId !== 0xFFFFFFFF) {{
    out.ok = false;
    out.fail = 'path is not type=2/id=-1; not submitting';
    return out;
  }}

  /* preflight: 0x8828460 -> 0x8875950 needs [ctx+0x58] -> +0x618 -> +8 */
  const ctx = liveContext(cpu, SLOT);
  const actorTable = gp(ctx + 0x58).readU64().toNumber();
  out.ctx = '0x' + ctx.toString(16);
  out.actor_table = '0x' + actorTable.toString(16);
  if (!req.client && actorTable === 0) {{
    out.ok = false;
    out.fail = 'actor id table missing ([ctx+0x58]=0); not submitting';
    return out;
  }}
  if (req.noSubmit) {{
    out.ok = false;
    out.fail = 'dry run: --no-submit';
    return out;
  }}

  let p2;
  if (req.client) {{
    const player = callGuest(cpu, 0x8525360, [0], null, null).ret;
    if (!player || gp(player + 4).readU32() !== req.actor)
      throw new Error('local player actor does not match requested handle');
    const id = gp(player + 8).readU32();
    const global = gp(0x914f840).readU64().toNumber();
    const world = gp(global + 0x10).readU64().toNumber();
    const tab = gp(world + 0xa98).readU64().toNumber();
    const shift = gp(tab + 0x168).readU32(), limit = gp(tab + 0x100).readU32();
    const index = id & 0xffff;
    if (index >= limit || shift > 16) throw new Error('invalid controller index');
    const buckets = gp(tab + 0x120).readU64().toNumber();
    const bucket = gp(buckets + (index >> shift) * 8).readU64().toNumber();
    const controller = bucket + (index & ((1 << shift) - 1)) * 0x410;
    if (gp(controller).readU32() !== id || gp(controller + 8).readU32() !== req.actor)
      throw new Error('controller does not belong to requested actor');
    out.controller = '0x' + controller.toString(16);
    out.route = 'client_world_command';
    const speed = req.approach ? Math.min(req.speed, Math.max(0.02, out.distance * 0.25)) : req.speed;
    out.command_speed = speed;
    p2 = callGuest(cpu, 0x80d21f0,
      [controller, 0x777c, 0x777c, path, 0, 0, 0, 0, 0], null, 0, speed);
  }} else {{
    p2 = callGuest(cpu, MOVE_SUBMIT, [req.actor, path, req.w2], null, req.speed);
  }}
  out.submit = {{ returned: p2.returned, pc_after: p2.pc, ret: '0x' + BigInt(p2.ret).toString(16) }};
  out.steps.push({{ step: 'move_submit', returned: p2.returned, hex: hexBytes(path, 0x20) }});

  /* position after the submit: the entity, never the handle */
  const afterEntity = entityFromHandle(req.actor);
  if (afterEntity === null) throw new Error('player handle expired after submit');
  const p3 = callGuest(cpu, ENTITY_POS, [afterEntity], cur, null);
  const after = hexBytes(cur, 16);
  out.after = {{ pos: [f32(after, 0), f32(after, 1), f32(after, 2)],
                w_u32: u32(after, 3), w_hex: '0x' + u32(after, 3).toString(16), hex: after }};
  out.steps.push({{ step: 'entity_pos_after', returned: p3.returned, hex: after }});
  return out;
}}

const frameHost = resolveGuest(FRAME);
if (frameHost) {{
  Interceptor.attach(frameHost, {{
    onEnter(args) {{
      if (parseInt(args[1].toString(), 16) !== FRAME) return;
      if (HOOK_EVENT !== null) {{
        const ev = args[0].readU64().toNumber();
        if (!ev || gp(ev).readU32() !== HOOK_EVENT || gp(ev+0x28).readU32() !== 0) return;
      }}
      this.cpu = args[0];
      this.lr = args[0].add(240).readU64().toNumber();
      if (!AFTER) perform(args[0]);
    }},
    onLeave() {{
      if (AFTER && this.cpu && this.cpu.add(PC).readU64().toNumber() === this.lr) perform(this.cpu);
    }}
  }});
}}
function perform(sourceCpu) {{
      frameCalls++;
      if (!armed || busy) return;
      if (CONTEXT !== null && SLOT !== null && liveContext(sourceCpu, SLOT) !== CONTEXT) return;
      const req = armed;
      armed = null;
      busy = true;
      /* The scheduler may concurrently set the original CPU.poll. Never restore
         an old poll value over it: all injected execution uses this copy. */
      const cpu = Memory.alloc(CPU_SIZE);
      Memory.copy(cpu, sourceCpu, CPU_SIZE);
      cpu.add(POLL).writeU32(0);
      cpu.add(248).writeU64(stackTop());
      const t0 = Date.now();
      let saved = null;
      try {{
        saved = saveState(cpu);
        if (req.mode === 'project') {{
          result = runProject(cpu, req);
        }} else if (req.mode === 'move') {{
          lastOut = null;
          result = runMove(cpu, req);
        }} else if (req.mode === 'write') {{
          result = runWrite(cpu, req);
        }} else {{
          result = runCall(cpu, req);
        }}
        result.ms = Date.now() - t0;
        result.cpu_isolated = true;
        if (req.mode === 'move') {{
          req.trace = req.trace || [];
          req.trace.push({{ pos: result.before.pos, target: result.target, distance: result.distance,
                           arrived: !!result.arrived, submitted: !!result.submit }});
          if (result.ok && !result.arrived && req.repeat > 1) {{
            req.repeat--; armed = req; result = null;
          }} else {{ result.trace = req.trace; }}
        }}
      }} catch (e) {{
        result = {{ ok: false, error: e.message, stack: e.stack, partial: lastOut }};
      }} finally {{
        try {{ if (saved) restoreState(cpu, saved); }}
        catch (e) {{ if (result) result.restore_error = e.message; }}
        busy = false;
      }}
}}
rpc.exports = {{
  arm(req) {{ armed = req; result = null; return true; }},
  result() {{ return {{ result, frameCalls, slot: SLOT, guest_stack: stackBase ? '0x' + stackBase.toString(16) : null,
                        frameHost: frameHost ? frameHost.toString() : null }}; }}
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--target", type=lambda s: int(s, 0))
    ap.add_argument("--arg", action="append", default=[], type=lambda s: int(s, 0), help="x0..x7, in order")
    ap.add_argument("--x8", default=None, help="'sp-0x4000' for stack scratch, or a guest address")
    ap.add_argument("--dump-len", type=int, default=16)
    ap.add_argument("--s0", type=float, default=None)
    ap.add_argument("--move", default=None, help="dx,dy,dz offsets from the actor's current position")
    ap.add_argument("--project", action="store_true", help="round-trip a world location through the engine camera")
    ap.add_argument("--offset", default="0,0,0", help="world offset for --project")
    ap.add_argument("--screen", default=None, help="optional engine pixel x,y for --project")
    ap.add_argument("--actor", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=None,
                    help="GetTlsValue context, to resolve the actor handle to its entity")
    ap.add_argument("--entity", type=lambda s: int(s, 0), default=None,
                    help="entity object address, instead of resolving --actor")
    ap.add_argument("--speed", type=float, default=6.0)
    ap.add_argument("--w2", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--no-submit", action="store_true", help="build and validate the path, do not call 0x8828460")
    ap.add_argument("--client", action="store_true", help="use observed native client world command 0x80D21F0")
    ap.add_argument("--repeat", type=int, default=1, help="repeat the same fixed world goal for at most this many frames")
    ap.add_argument("--radius", type=float, default=0.3)
    ap.add_argument("--approach", action="store_true", help="reduce native command speed near the fixed target")
    ap.add_argument("--write", type=lambda s: int(s, 0), default=None, help="guest address to write 16 bytes of floats")
    ap.add_argument("--floats", default=None, help="x,y,z,w for --write")
    ap.add_argument("--frame", type=lambda s: int(s, 0), default=FRAME, help="guest frame hook point")
    ap.add_argument("--after", action="store_true", help="run only after the selected frame function fully returns")
    ap.add_argument("--event", type=lambda s: int(s, 0), default=None, help="require this player-0 input event type")
    ap.add_argument("--wait", type=float, default=10.0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    assert_installed()
    if args.project:
        if args.actor is None:
            raise SystemExit("--project needs --actor")
        req = {"mode": "project", "actor": args.actor,
               "offset": [float(x) for x in args.offset.split(",")],
               "screen": [float(x) for x in args.screen.split(",")] if args.screen else None}
    elif args.write is not None:
        if not args.floats:
            raise SystemExit("--write needs --floats x,y,z,w")
        req = {"mode": "write", "addr": args.write,
               "floats": [float(v) for v in args.floats.split(",")]}
    elif args.move:
        if args.actor is None:
            raise SystemExit("--move needs --actor")
        dx, dy, dz = (float(v) for v in args.move.split(","))
        req = {"mode": "move", "actor": args.actor, "entity": args.entity, "dx": dx, "dy": dy, "dz": dz,
               "speed": args.speed, "w2": args.w2, "noSubmit": args.no_submit, "client": args.client,
               "repeat": args.repeat, "radius": args.radius, "approach": args.approach}
    else:
        if args.target is None:
            raise SystemExit("--target or --move is required")
        x8 = None
        x8_rel = 0
        if args.x8:
            if args.x8.startswith("sp-"):
                x8_rel = int(args.x8[3:], 0)
            else:
                x8 = int(args.x8, 0)
        req = {"mode": "call", "target": args.target, "args": args.arg, "x8": x8, "x8Rel": x8_rel,
               "s0": args.s0, "dumpLen": args.dump_len}

    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS.replace("__CONTEXT__", hex(args.context) if args.context else "null")
                                     .replace("__FRAME__", hex(args.frame))
                                     .replace("__AFTER__", "true" if args.after else "false")
                                     .replace("__EVENT__", hex(args.event) if args.event is not None else "null"))
    script.on("message", lambda m, d: print("js:", m.get("payload", m), flush=True))
    script.load()
    api = script.exports_sync
    data = {}
    try:
        api.arm(req)
        deadline = time.time() + args.wait
        while time.time() < deadline:
            data = api.result()
            if data.get("result"):
                break
            time.sleep(0.1)
    finally:
        session.detach()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
