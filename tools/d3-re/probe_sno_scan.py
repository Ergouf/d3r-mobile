#!/usr/bin/env python3
"""Read-only entity scan: SNO, position, controller and flags. No guest calls.

Walks the same bucket table as probe_entities.py. Distances are horizontal.
A missing context or an unreadable table is an error, never an empty scene.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

HOLDER = 0x914F8D0


def build_js(context: int, near: tuple[float, float, float], radius: float) -> str:
    return js_consts() + f"""
const CONTEXT = {context};
const NEAR = [{near[0]}, {near[1]}, {near[2]}];
const RADIUS = {radius};
const HOLDER = 0x{HOLDER:x};
function num(v) {{ return typeof v === 'number' ? v : v.toNumber(); }}
function gp(addr) {{ return gm.add(num(addr)); }}
function g32(addr) {{ try {{ return gp(addr).readU32(); }} catch (e) {{ return null; }} }}
function g64n(addr) {{ try {{ return gp(addr).readU64().toNumber(); }} catch (e) {{ return null; }} }}
function gf(addr) {{ try {{ return gp(addr).readFloat(); }} catch (e) {{ return null; }} }}
const a = g64n(CONTEXT);
const b = a ? g64n(a) : null;
const c = b ? g64n(b + 0x198) : null;
const table = c ? g64n(c) : null;
if (!table) {{
  send({{ ok:false, error:'entity table unresolved', holder:HOLDER }});
}} else {{
  const count = g32(table + 0x100), shift = g32(table + 0x168), buckets = g64n(table + 0x120);
  if (count === null || shift === null || buckets === null || buckets === 0 ||
      shift < 0 || shift > 16 || !(count > 0) || count > 100000) {{
    send({{ ok:false, error:'table layout mismatch', table, count, shift, buckets }});
  }} else {{
    const per = 1 << shift;
    const nb = Math.ceil(count / per);
    const bases = [];
    for (let i = 0; i < nb; i++) bases.push(g64n(buckets + i * 8));
    const out = [];
    let rejected = 0;
    for (let index = 0; index < count; index++) {{
      const base = bases[index >> shift];
      if (!base) {{ rejected++; continue; }}
      const entry = base + (index & (per - 1)) * 0x360;
      const handle = g32(entry);
      if (handle === null || (handle & 0xffff) !== index) {{ rejected++; continue; }}
      const x = gf(entry + 0x60), y = gf(entry + 0x64), z = gf(entry + 0x68);
      if (x === null || y === null || z === null) {{ rejected++; continue; }}
      const dist = Math.hypot(x - NEAR[0], y - NEAR[1]);
      if (!Number.isFinite(dist) || dist > RADIUS) continue;
      out.push([handle, g32(entry + 0x18), g32(entry + 0x14c), g32(entry + 0x14),
                x, y, z, g32(entry + 0xa0), gp(entry + 0x160).readU16(), dist, entry]);
    }}
    out.sort((p, q) => p[9] - q[9]);
    if (rejected === count) {{
      send({{ ok:false, error:'entity table unreadable', table, count, shift, rejected }});
    }} else send({{ ok:true, table, count, shift, rejected, in_radius: out.length,
            rows: out.map(e => ({{id:e[0], sno:e[1], type:e[2], ctrl:e[3],
              x:e[4], y:e[5], z:e[6], place:e[7], flags:e[8], dist:e[9], entry:e[10]}})) }});
  }}
}}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--near", required=True)
    ap.add_argument("--radius", type=float, default=450)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    near = tuple(float(v) for v in args.near.split(","))
    if len(near) != 3:
        ap.error("--near must be x,y,z")
    build = assert_installed()
    payload = {}
    errors = []
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(build_js(args.context, near, args.radius))
        def on_message(message, _data):
            if message.get("type") == "error":
                errors.append(message)
            else:
                payload.update(message.get("payload") or {"message": message})
        script.on("message", on_message)
        script.load()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not payload and not errors:
            time.sleep(0.05)
    finally:
        session.detach()
    if errors or payload.get("ok") is not True:
        raise SystemExit(f"scan failed: {payload or errors}")
    result = {"pid": args.pid, "build": build, "near": near, "radius": args.radius, **payload}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"in_radius {payload['in_radius']} table_count {payload['count']} rejected {payload['rejected']}")


if __name__ == "__main__":
    main()
