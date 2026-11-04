#!/usr/bin/env python3
"""Read the game thread's ``nn::os::GetTlsValue`` context and walk the entity table chain.

``0x800E3D0`` is ``ldr w0,[x0,#0xC]; b <GOT 0x914E6C0>``, i.e. ``nn::os::GetTlsValue(slot)``.
The GOT target in this build is ``0x9DDF40``::

    mrs  x8, tpidrro_el0
    ldr  x8, [x8, #0x1F8]
    add  x8, x8, w0, uxtw #3
    ldr  x0, [x8, #0x80]
    ret

so the context depends on the calling guest thread's TPIDRRO_EL0, which lives in the runtime's
``CPU`` struct (``tpidrro`` at +808).  This probe hooks the guest getter, records the return
value of real calls per guest thread, and reads that thread's TPIDRRO_EL0 to reproduce the same
value.  It then walks ``[ctx] -> [ctx] -> [+0x198] -> [table]`` and checks the bucket layout.

Read-only: it writes no guest memory and makes no guest calls.

Usage:
  python tools/d3-re/probe_tls_context.py --pid <pid> [--seconds 5] [--out out/windows/kbm/tls.json]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

GETTER = 0x800E3D0       # nn::os::GetTlsValue wrapper used by every entity lookup
HOLDER = 0x914F8D0       # *(holder) is the object whose +0xC is the TLS slot
GOT_TLS = 0x914E6C0      # jmprel slot that 0x800E3D0 jumps through
HID_UPDATE = 0x80FC310   # engine HID device update, every frame
DISPATCH = 0x82B80C0     # input event dispatch (event*, player, flag)

JS = js_consts() + f"""
const GETTER = 0x{GETTER:x}, HOLDER = 0x{HOLDER:x}, GOT_TLS = 0x{GOT_TLS:x};
const HID_UPDATE = 0x{HID_UPDATE:x}, DISPATCH = 0x{DISPATCH:x};

function num(v) {{ return typeof v === 'number' ? v : v.toNumber(); }}
function gp(a) {{ return gm.add(num(a)); }}
function g32(a) {{ try {{ return gp(a).readU32(); }} catch (e) {{ return null; }} }}
function g64(a) {{ try {{ return gp(a).readU64(); }} catch (e) {{ return null; }} }}
function g64n(a) {{ const v = g64(a); return v === null ? null : v.toNumber(); }}
function hex(v) {{ return v === null || v === undefined ? null : '0x' + v.toString(16); }}
function mapped(a) {{
  if (a === null || a === undefined) return null;
  try {{
    const r = Process.findRangeByAddress(gp(a));
    return r ? {{ base: r.base.toString(), size: r.size, protection: r.protection }} : null;
  }} catch (e) {{ return null; }}
}}
function hexBytes(a, n) {{
  try {{ return Array.from(new Uint8Array(gp(a).readByteArray(n)), b => b.toString(16).padStart(2, '0')).join(''); }}
  catch (e) {{ return 'err:' + e.message; }}
}}

/* [ctx] -> [ctx] -> [+0x198] -> [table], exactly as 0x866D5C0 / 0x8828460 walk it. */
function walk(context) {{
  const a = g64n(context);
  const b = a === null ? null : g64n(a);
  const c = b === null ? null : g64n(b + 0x198);
  const table = c === null ? null : g64n(c);
  const out = {{ context: hex(context), chain: [hex(a), hex(b), hex(c), hex(table)] }};
  if (table === null) {{ out.error = 'chain unreadable'; return out; }}
  out.table = hex(table);
  out.table_range = mapped(table);
  out.count = g32(table + 0x100);
  out.shift = g32(table + 0x168);
  out.buckets = hex(g64n(table + 0x120));
  out.buckets_range = mapped(g64n(table + 0x120));
  out.sane = out.count !== null && out.shift !== null && out.buckets !== null &&
             out.count > 0 && out.count <= 100000 && out.shift >= 0 && out.shift <= 16;
  return out;
}}

const out = {{
  getter: GETTER, holder: null, slot: null, got_tls_impl: null, got_tls_impl_range: null,
  got_tls_bytes: null, threads: {{}}, dispatch: null, hid: null, calls: 0, errors: []
}};

out.holder = hex(g64n(HOLDER));
if (out.holder !== null) {{
  out.holder_range = mapped(g64n(HOLDER));
  const obj = g64n(g64n(HOLDER));
  out.holder_obj = hex(obj);
  out.holder_obj_range = mapped(obj);
  if (obj !== null) out.slot = g32(obj + 0xC);
}}
const impl = g64n(GOT_TLS);
out.got_tls_impl = hex(impl);
out.got_tls_impl_range = mapped(impl);
if (impl !== null) out.got_tls_bytes = hexBytes(impl, 0x40);

function cpuTls(cpu) {{
  const r = {{}};
  try {{ r.tpidr = cpu.add(800).readU64().toString(); }} catch (e) {{ r.tpidr = null; }}
  try {{ r.tpidrro = cpu.add(808).readU64().toString(); }} catch (e) {{ r.tpidrro = null; }}
  return r;
}}

const getterHost = resolveGuest(GETTER);
out.getter_host = getterHost ? getterHost.toString() : null;
let getterListener = null;
if (getterHost) {{
  getterListener = Interceptor.attach(getterHost, {{
    onEnter(args) {{
      out.calls++;
      if (out.calls > 6000) {{ try {{ getterListener.detach(); }} catch (e) {{}} return; }}
      try {{
        const tid = Process.getCurrentThreadId();
        const tls = cpuTls(args[0]);
        const rec = out.threads[tid] || {{ tid, tpidr: tls.tpidr, tpidrro: tls.tpidrro, calls: 0, rets: {{}} }};
        rec.calls++;
        out.threads[tid] = rec;
        this.cpu = args[0];
        this.tid = tid;
      }} catch (e) {{ if (out.errors.length < 8) out.errors.push('getter: ' + e.message); }}
    }},
    onLeave() {{
      try {{
        const rec = out.threads[this.tid];
        if (!rec || !this.cpu) return;
        /* guest x0 after the call is the value GetTlsValue returned on this thread */
        const ret = this.cpu.add(0).readPointer().toString();
        rec.rets[ret] = (rec.rets[ret] || 0) + 1;
      }} catch (e) {{ if (out.errors.length < 8) out.errors.push('leave: ' + e.message); }}
    }}
  }});
}}

function hookThread(pc, slotName) {{
  const host = resolveGuest(pc);
  if (!host) return null;
  Interceptor.attach(host, {{
    onEnter(args) {{
      try {{
        const tls = cpuTls(args[0]);
        out[slotName] = {{ tid: Process.getCurrentThreadId(), tpidr: tls.tpidr, tpidrro: tls.tpidrro,
                          cpu: args[0].toString() }};
      }} catch (e) {{ if (out.errors.length < 8) out.errors.push(slotName + ': ' + e.message); }}
    }}
  }});
  return host.toString();
}}
out.hid_host = hookThread(HID_UPDATE, 'hid');
out.dispatch_host = hookThread(DISPATCH, 'dispatch');

/* Reproduce GetTlsValue from a thread's TPIDRRO_EL0 (0x9DDF40). */
function tlsContext(tpidrro, slot) {{
  const block = g64n(tpidrro + 0x1F8);
  if (block === null) return {{ slot, error: 'tpidrro+0x1F8 unreadable' }};
  const ctx = g64n(block + 0x80 + slot * 8);
  return {{ slot, block: hex(block), context: hex(ctx) }};
}}
function probeTls(tpidrro) {{
  const res = [];
  for (let slot = 0; slot < 16; slot++) {{
    const t = tlsContext(tpidrro, slot);
    if (!t.context || t.context === '0x0') {{ res.push({{ slot, block: t.block, context: t.context, sane: false }}); continue; }}
    const w = walk(parseInt(t.context, 16));
    res.push({{ slot, block: t.block, context: t.context, count: w.count, shift: w.shift,
               buckets: w.buckets, sane: w.sane, error: w.error }});
  }}
  return res;
}}

rpc.exports = {{
  data() {{ return out; }},
  tls(tpidrro) {{ return probeTls(Number(tpidrro)); }},
  context(tpidrro, slot) {{ return tlsContext(Number(tpidrro), slot); }},
  walk(contextHex) {{ return walk(parseInt(contextHex, 16)); }}
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=5.0, help="observation window")
    ap.add_argument("--out", type=Path, default=Path("out/windows/kbm/tls-context.json"))
    args = ap.parse_args()

    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("js:", m.get("payload", m), flush=True))
    script.load()
    api = script.exports_sync
    data = {}
    try:
        time.sleep(args.seconds)
        data = api.data()
        print(json.dumps({k: v for k, v in data.items() if k != "threads"}, indent=2, ensure_ascii=False))
        threads = sorted(data.get("threads", {}).values(), key=lambda r: -r["calls"])
        print("threads:")
        for rec in threads:
            print("  ", rec)
        slot = data.get("slot")
        data["by_thread"] = {}
        for rec in threads[:3]:
            if not rec.get("tpidrro") or slot is None:
                continue
            ctx = api.context(rec["tpidrro"], slot)
            ctx["walk"] = api.walk(ctx["context"]) if ctx.get("context") else None
            ctx["tls"] = api.tls(rec["tpidrro"])
            data["by_thread"][rec["tid"]] = ctx
            print("tid", rec["tid"], "tpidrro", rec["tpidrro"], "slot", slot, "->", ctx["context"],
                  "sane", bool(ctx["walk"] and ctx["walk"].get("sane")),
                  "count", ctx["walk"].get("count") if ctx["walk"] else None)
        for rec in threads[:2]:
            if not rec.get("tpidrro"):
                continue
            print("tls slots of tid", rec["tid"], "tpidrro", rec["tpidrro"])
            for row in data["by_thread"].get(rec["tid"], {}).get("tls", []):
                if row.get("sane") or row.get("context") not in (None, "0x0"):
                    print("   ", row)
    finally:
        session.detach()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
