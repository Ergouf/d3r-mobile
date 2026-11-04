#!/usr/bin/env python3
"""Inspect the entity-table pointer chain and validate the table's bucket layout.

This replaces the old "walk nearby pointers and call every value a candidate" probe.
All addresses are guest addresses read through ``g_mem``; a value read from guest
memory is not a host pointer.  The chain the game uses is:

  holder = [0x914F8D0]            guest pointer to the holder object
  slot   = [holder + 0xC]         nn::os::TlsSlot for GetTlsValue
  context= nn::os::GetTlsValue(slot)   per guest thread; this probe cannot call it
  a      = [context]
  b      = [a]
  c      = [b + 0x198]
  table  = [c]

Because the context is per-thread, pass ``--context`` (the value a game-thread probe
read from GetTlsValue) or ``--table`` (the table object) to validate the layout.
Without either, the probe prints the holder and slot and stops; it does not report a
"no candidates" result that could be mistaken for evidence.

Table layout (0x88284B4): count at +0x100, bucket array guest pointer at +0x120,
shift at +0x168, entry stride 0x360, entry[0] is the full handle.

Usage:
  python tools/d3-re/probe_entity_table.py --pid <pid> [--context 0x... | --table 0x...]
"""
from __future__ import annotations

import argparse
import time

import frida

from version import assert_installed, js_consts


def build_js(table: int | None, context: int | None) -> str:
    return (
        js_consts()
        + f"""
const TABLE = {hex(table) if table else 'null'};
const CONTEXT = {hex(context) if context else 'null'};

function num(v) {{ return typeof v === 'number' ? v : v.toNumber(); }}
function gp(addr) {{ return gm.add(num(addr)); }}
function g32(addr) {{ try {{ return gp(addr).readU32(); }} catch (e) {{ return null; }} }}
function g64(addr) {{ try {{ return gp(addr).readU64(); }} catch (e) {{ return null; }} }}
function g64n(addr) {{ const v = g64(addr); return v === null ? null : v.toNumber(); }}
function hex(v) {{ return v === null || v === undefined ? null : '0x' + v.toString(16); }}

const holder = g64n(0x914F8D0);
const slot = holder === null ? null : g32(holder + 0xC);
const out = {{ holder: hex(holder), tls_slot: slot }};
if (TABLE !== null) {{
  out.table = hex(TABLE);
}} else if (CONTEXT !== null) {{
  const a = g64n(CONTEXT), b = a ? g64n(a) : null;
  const c = b ? g64n(b + 0x198) : null;
  out.context = hex(CONTEXT);
  out.context_chain = [hex(a), hex(b), hex(c)];
  out.table = c ? hex(g64n(c)) : null;
}} else {{
  out.error = 'the context is per-thread: pass --context (GetTlsValue result) or --table';
}}
if (out.table) {{
  const t = parseInt(out.table, 16);
  const count = g32(t + 0x100), shift = g32(t + 0x168), buckets = g64n(t + 0x120);
  out.count = count;
  out.shift = shift;
  out.buckets = hex(buckets);
  out.bucket_layout_ok = count !== null && count >= 0 && count <= 100000 && shift !== null &&
                         shift >= 0 && shift <= 16 && buckets !== null;
  if (out.bucket_layout_ok) {{
    const per = 1 << shift, nbuckets = Math.ceil(count / per);
    let unreadable = 0;
    for (let b = 0; b < nbuckets; b++) if (g64n(buckets + b * 8) === null) unreadable++;
    out.buckets_used = nbuckets;
    out.unreadable_buckets = unreadable;
    out.entry_stride = 0x360;
  }}
}}
send(out);
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--table", type=lambda s: int(s, 0), help="entity table object, guest address")
    ap.add_argument("--context", type=lambda s: int(s, 0),
                    help="GetTlsValue result on the game thread, guest address")
    args = ap.parse_args()
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(build_js(args.table, args.context))
    script.on("message", lambda m, d: print(m.get("payload", m), flush=True))
    script.load()
    time.sleep(1.5)
    session.detach()


if __name__ == "__main__":
    main()
