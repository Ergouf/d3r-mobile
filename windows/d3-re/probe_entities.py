#!/usr/bin/env python3
"""Enumerate the engine's entity table by its real bucket layout and find entries near a point.

Every address in this probe is a *guest* address read through the runtime's ``g_mem``
translation (``gm.add(guest)``).  A value read from guest memory is never passed to
``ptr()`` as a host pointer: guest and host addresses live in different spaces.

The table is reached in the game through ``nn::os::GetTlsValue`` (``0x800E3D0``), so a
Frida thread cannot resolve it from ``[0x914F8D0]`` alone.  Supply either:

  --context <guest>  the value GetTlsValue returned on the game/input thread; the probe
                     follows [context] -> [that] -> [that+0x198] -> [that] to the table
  --table <guest>    the table object itself

Without one of them the probe reports the holder and TLS slot it can see and exits
without an entity count; it does not turn "could not resolve" into "0 entities".

Layout used by the lookup at ``0x88284B4`` (not a linked list):

  count          u32 at table + 0x100
  bucket array   guest pointer at table + 0x120
  bucket shift   u32 at table + 0x168
  index          handle & 0xFFFF
  bucket         index >> shift
  slot           index & ((1 << shift) - 1)
  entry          buckets[bucket] + slot * 0x360
  handle         u32 at entry + 0
  position       floats at entry + 0x60 / +0x64 / +0x68

Usage:
  python windows/d3-re/probe_entities.py --pid <pid> --table 0x... [--near 2941,2829,24]
  python windows/d3-re/probe_entities.py --pid <pid> --context 0x... [--limit 20]
"""
from __future__ import annotations

import argparse
import time

import frida

from version import assert_installed, js_consts

HOLDER = 0x914F8D0
STRIDE = 0x360


def build_js(table: int | None, context: int | None, near: tuple[float, float, float], limit: int) -> str:
    return (
        js_consts()
        + f"""
const TABLE = {hex(table) if table else 'null'};
const CONTEXT = {hex(context) if context else 'null'};
const NEAR = [{near[0]}, {near[1]}, {near[2]}];
const HOLDER = 0x{HOLDER:x}, STRIDE = 0x{STRIDE:x};

/* UInt64 from readU64() is not a Number: convert before adding it to a NativePointer. */
function num(v) {{ return typeof v === 'number' ? v : v.toNumber(); }}
function gp(addr) {{ return gm.add(num(addr)); }}
function g32(addr) {{ try {{ return gp(addr).readU32(); }} catch (e) {{ return null; }} }}
function g64(addr) {{ try {{ return gp(addr).readU64(); }} catch (e) {{ return null; }} }}
function g64n(addr) {{ const v = g64(addr); return v === null ? null : v.toNumber(); }}
function gf(addr) {{ try {{ return gp(addr).readFloat(); }} catch (e) {{ return null; }} }}
function hex(v) {{ return v === null || v === undefined ? null : '0x' + v.toString(16); }}

let table = TABLE;
if (table === null && CONTEXT !== null) {{
  const a = g64n(CONTEXT);
  const b = a ? g64n(a) : null;
  const c = b ? g64n(b + 0x198) : null;
  table = c ? g64n(c) : null;
}}
if (table === null) {{
  const holder = g64n(HOLDER);
  const slot = holder === null ? null : g32(holder + 0xC);
  send({{ error: 'the entity table needs the game thread\\'s TLS value; pass --context or --table',
          holder: hex(holder), tls_slot: slot }});
}} else {{
  const count = g32(table + 0x100), shift = g32(table + 0x168), buckets = g64n(table + 0x120);
  send({{ table: hex(table), count, shift, buckets: hex(buckets) }});
  if (count === null || shift === null || buckets === null || shift < 0 || shift > 16 || count > 100000) {{
    send({{ error: 'table layout mismatch', table: hex(table), count, shift, buckets: hex(buckets) }});
  }} else {{
    const per = 1 << shift;
    const nbuckets = Math.ceil(count / per);
    const bases = [];
    let unreadable = 0;
    for (let b = 0; b < nbuckets; b++) {{
      const base = g64n(buckets + b * 8);
      if (base === null) unreadable++;
      bases.push(base);
    }}
    const out = [];
    let bad = 0;
    for (let index = 0; index < count; index++) {{
      const base = bases[index >> shift];
      if (base === null) {{ bad++; continue; }}
      const entry = base + (index & (per - 1)) * STRIDE;
      const handle = g32(entry);
      /* the engine checks entry[0] against the full handle; the low 16 bits are the index */
      if (handle === null || (handle & 0xffff) !== index) {{ bad++; continue; }}
      const x = gf(entry + 0x60), y = gf(entry + 0x64), z = gf(entry + 0x68);
      if (x === null || y === null || z === null) {{ bad++; continue; }}
      const d = Math.abs(x - NEAR[0]) + Math.abs(y - NEAR[1]) + Math.abs(z - NEAR[2]);
      out.push([d, handle, x, y, z, entry]);
    }}
    out.sort((a, b) => a[0] - b[0]);
    send({{ count, shift, per_bucket: per, buckets_used: nbuckets, unreadable_buckets: unreadable,
            valid_entries: out.length, rejected_slots: bad,
            nearest: out.slice(0, {limit}).map(e => [e[1], e[2], e[3], e[4], hex(e[5])]) }});
  }}
}}
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--table", type=lambda s: int(s, 0), help="entity table object, guest address")
    ap.add_argument("--context", type=lambda s: int(s, 0),
                    help="GetTlsValue result on the game thread, guest address")
    ap.add_argument("--near", default="2941,2829,24")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    near = tuple(float(v) for v in args.near.split(","))
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(build_js(args.table, args.context, near, args.limit))
    script.on("message", lambda m, d: print(m.get("payload", m), flush=True))
    script.load()
    time.sleep(3)
    session.detach()


if __name__ == "__main__":
    main()
