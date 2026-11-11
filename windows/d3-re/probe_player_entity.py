#!/usr/bin/env python3
"""Identify the player entity by moving it and diffing the entity table (read-only).

Takes the entity table from the game thread's ``GetTlsValue`` context (see
``probe_tls_context.py``), snapshots every valid entry's position, posts one real key
(``Post-GameInput.ps1``, no focus needed), snapshots again, and reports the entries whose
position changed.  The camera target fields found in ``round9`` are read too, so the player
candidate can be checked against the camera rather than only by motion.

Read-only: no guest memory is written; the key goes through the game's own SDL keyboard path.

Usage:
  python windows/d3-re/probe_player_entity.py --pid <pid> --context 0x... [--key w] [--hold-ms 1500]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

STRIDE = 0x360
CAMERA_TARGETS = (0x09804A28, 0x09862E68, 0x0990CC5C)
CAMERA_POS = 0x09862EAC

JS = js_consts() + f"""
const CONTEXT = __CONTEXT__;
const STRIDE = 0x{STRIDE:x};
const TARGETS = [{', '.join(hex(a) for a in CAMERA_TARGETS)}];
const CAMERA = 0x{CAMERA_POS:x};

function num(v) {{ return typeof v === 'number' ? v : v.toNumber(); }}
function gp(a) {{ return gm.add(num(a)); }}
function g32(a) {{ try {{ return gp(a).readU32(); }} catch (e) {{ return null; }} }}
function g64n(a) {{ try {{ return gp(a).readU64().toNumber(); }} catch (e) {{ return null; }} }}
function gf(a) {{ try {{ return gp(a).readFloat(); }} catch (e) {{ return null; }} }}
function vec3(a) {{ const x = gf(a), y = gf(a + 4), z = gf(a + 8); return x === null || y === null || z === null ? null : [x, y, z]; }}

function tableFromContext(context) {{
  const a = g64n(context);
  const b = a === null ? null : g64n(a);
  const c = b === null ? null : g64n(b + 0x198);
  return c === null ? null : g64n(c);
}}
const TABLE = tableFromContext(CONTEXT);
const COUNT = TABLE === null ? null : g32(TABLE + 0x100);
const SHIFT = TABLE === null ? null : g32(TABLE + 0x168);
const BUCKETS = TABLE === null ? null : g64n(TABLE + 0x120);

function scan() {{
  const out = {{ table: TABLE, count: COUNT, shift: SHIFT, targets: TARGETS.map(vec3),
                camera: vec3(CAMERA), entities: [], bad: 0 }};
  if (TABLE === null || COUNT === null || SHIFT === null || BUCKETS === null) {{
    out.error = 'table unresolved';
    return out;
  }}
  const per = 1 << SHIFT;
  const bases = [];
  for (let b = 0; b < Math.ceil(COUNT / per); b++) bases.push(g64n(BUCKETS + b * 8));
  for (let index = 0; index < COUNT; index++) {{
    const base = bases[index >> SHIFT];
    if (base === null) {{ out.bad++; continue; }}
    const entry = base + (index & (per - 1)) * STRIDE;
    const handle = g32(entry);
    if (handle === null || (handle & 0xffff) !== index) {{ out.bad++; continue; }}
    const p = vec3(entry + 0x60);
    if (p === null) {{ out.bad++; continue; }}
    out.entities.push([handle, p[0], p[1], p[2], entry]);
  }}
  return out;
}}

rpc.exports = {{ scan }};
"""


def post_key(key: str, hold_ms: int, pid: int) -> None:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    "windows/tools/Post-GameInput.ps1", "-Key", key, "-HoldMs", str(hold_ms),
                    "-ProcessId", str(pid)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--key", default="w")
    ap.add_argument("--hold-ms", type=int, default=1500)
    ap.add_argument("--out", type=Path, default=Path("out/windows/kbm/player-entity.json"))
    args = ap.parse_args()

    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS.replace("__CONTEXT__", hex(args.context)))
    script.on("message", lambda m, d: print("js:", m.get("payload", m), flush=True))
    script.load()
    api = script.exports_sync
    try:
        before = api.scan()
        print("table", before.get("table"), "count", before.get("count"), "shift", before.get("shift"),
              "entities", len(before["entities"]), "rejected", before.get("bad"))
        print("targets", before.get("targets"), "camera", before.get("camera"))
        post_key(args.key, args.hold_ms, args.pid)
        time.sleep(0.6)
        after = api.scan()
    finally:
        session.detach()

    prev = {e[0]: e for e in before["entities"]}
    moved = []
    for e in after["entities"]:
        p = prev.get(e[0])
        if not p:
            continue
        d = ((e[1] - p[1]) ** 2 + (e[2] - p[2]) ** 2 + (e[3] - p[3]) ** 2) ** 0.5
        moved.append({"handle": e[0], "dx": e[1] - p[1], "dy": e[2] - p[2], "dz": e[3] - p[3],
                      "dist": d, "before": p[1:4], "after": e[1:4], "entry": hex(e[4])})
    moved.sort(key=lambda r: -r["dist"])
    print(f"moved (>{0.05}):")
    for rec in [m for m in moved if m["dist"] > 0.05][:12]:
        print(f"  handle {rec['handle']} d={rec['dist']:.3f} ({rec['dx']:+.2f},{rec['dy']:+.2f},{rec['dz']:+.2f})"
              f" {rec['before']} -> {rec['after']} {rec['entry']}")
    if moved:
        print("largest:", moved[0]["handle"], "dist", round(moved[0]["dist"], 3))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"before": before, "after": after, "moved": moved}, indent=2),
                        encoding="utf-8")


if __name__ == "__main__":
    main()
