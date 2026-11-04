#!/usr/bin/env python3
"""Bounded observer for the D3 guest UI event dispatch (correct host ABI).

GuestFn on the x64 host is (CPU*, guest_entry): guest x0..xN live in CPU.x,
never in Frida's x64 context. This records the event object and its payload
for a small set of guest entry points, plus the guest LR so the caller can be
identified. Read-only: it never injects input or calls guest code.

Defaults are tied to runtime SHA-256 254fb541e06b3490eaddb41f49da6ba4
872b5e5604e0648a2e354f76784f3aba. Re-derive g_mem/g_disp/g_code_lo with
llvm-nm after a rebuild.

Usage:
  python tools/d3-re/trace_ui_events.py --pid <pid> --out out/windows/kbm/ui-events.json --seconds 8
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

import frida

JS = r"""
const P = PAYLOAD;
const exe = Process.enumerateModules().find(m => m.name.toLowerCase() === '01001b300b9be000.exe');
if (!exe) throw new Error('Game runtime not loaded');
const gm = exe.base.add(P.g_mem).readPointer();
const disp = exe.base.add(P.g_disp).readPointer();
const lo = exe.base.add(P.g_code_lo).readU64().toNumber();
const hi = exe.base.add(P.g_code_hi).readU64().toNumber();
const mod = Process.getModuleByName('01001B300B9BE000_code.dll');
function resolve(g) {
  if (g < lo || g >= hi || (g % 4)) return null;
  const f = disp.add(((g - lo) / 4) * 8).readPointer();
  return f.isNull() ? null : f;
}
const listeners = [];
const stats = {};
const hex = p => { try { return Array.from(new Uint8Array(p.readByteArray(64)), b => b.toString(16).padStart(2, '0')).join(''); } catch (e) { return null; } };
function sample(spec, cpu, lr) {
  const x = [0, 1, 2, 3].map(i => cpu.add(i * 8).readPointer());
  const rec = { x0: x[0].toString(), x1: x[1].toString(), x2: x[2].toString(),
                lr: lr.toString(), pc: cpu.add(0x100).readPointer().toString(),
                thread: cpu.add(0x378).readPointer().toString() };
  rec.args = [];
  for (const off of spec.read || []) {
    try { rec.args.push({ off, u32: gm.add(x[0].add(off)).readU32(), s: (() => { try { return gm.add(x[0].add(off)).readFloat(); } catch (e) { return null; } })() }); }
    catch (e) { rec.args.push({ off, error: 'unreadable' }); }
  }
  rec.event_hex = spec.hex ? hex(gm.add(x[1])) : null;
  rec.payload_hex = spec.hex ? hex(gm.add(x[2])) : null;
  try { rec.event_type = gm.add(x[1]).readU32(); } catch (e) { rec.event_type = null; }
  try { rec.payload_type = gm.add(x[2]).readU32(); } catch (e) { rec.payload_type = null; }
  return rec;
}
function hook(spec) {
  const host = resolve(spec.guest);
  const key = '0x' + spec.guest.toString(16);
  const st = stats[key] = { guest: spec.guest, host: host ? host.toString() : null, calls: 0, errors: 0,
    by_event_type: {}, by_payload_type: {}, by_lr: {}, threads: {}, samples: [] };
  if (!host) return;
  listeners.push(Interceptor.attach(host, { onEnter(args) {
    st.calls++;
    try {
      const cpu = args[0];
      if (!cpu.add(0x350).readPointer().equals(gm)) throw new Error('CPU* mismatch');
      const lr = cpu.add(30 * 8).readPointer();
      st.threads[String(this.threadId)] = (st.threads[String(this.threadId)] || 0) + 1;
      st.by_lr[lr.toString()] = (st.by_lr[lr.toString()] || 0) + 1;
      let et = null, pt = null;
      try { et = gm.add(cpu.add(8).readPointer()).readU32(); } catch (e) {}
      try { pt = gm.add(cpu.add(16).readPointer()).readU32(); } catch (e) {}
      st.by_event_type[String(et)] = (st.by_event_type[String(et)] || 0) + 1;
      st.by_payload_type[String(pt)] = (st.by_payload_type[String(pt)] || 0) + 1;
      const only = P.only_types || [];
      if (only.length && only.indexOf(et) < 0) return;
      if (st.samples.length < P.samples) st.samples.push(sample(spec, cpu, lr));
    } catch (err) {
      st.errors++;
      if (st.errors <= 2) send({ event: 'callback_error', target: key, error: err.message });
    }
  }}));
}
rpc.exports = {
  info() { return { arch: Process.arch, exe: exe.path, gmem: gm.toString(), code_lo: lo, code_hi: hi }; },
  watch(specs) { for (const s of specs) hook(s); return { event: 'ready', stats, hooks: listeners.length }; },
  counts() { return stats; }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seconds", type=float, default=6)
    ap.add_argument("--guest", type=lambda x: int(x, 0), action="append", default=[],
                    help="Guest entry to observe; default 0x83bad40")
    ap.add_argument("--read", default="", help="Comma-separated x0-relative u32/float offsets to sample")
    ap.add_argument("--hex", action="store_true", help="Save 64 bytes of event and payload")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--only-types", default="", help="Comma-separated event types to sample (counts stay complete)")
    ap.add_argument("--g-mem", type=lambda x: int(x, 0), default=0x17AEF20)
    ap.add_argument("--g-disp", type=lambda x: int(x, 0), default=0x12910E0)
    ap.add_argument("--g-code-lo", type=lambda x: int(x, 0), default=0x17AF028)
    ap.add_argument("--g-code-hi", type=lambda x: int(x, 0), default=0x17AF030)
    ap.add_argument("--expected-runtime-sha256",
                    default="f64723c0d627cd91e553fc739f042136b5d3004397b3b8148ec53294140458a7")
    args = ap.parse_args()
    if not 1 <= args.seconds <= 120:
        ap.error("seconds must be 1..120")
    guests = args.guest or [0x83BAD40]
    specs = [{"guest": g, "hex": args.hex,
              "read": [int(o, 0) for o in args.read.split(",") if o.strip()]} for g in guests]
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"pid": args.pid, "started_utc": datetime.now(timezone.utc).isoformat(),
              "guests": [hex(g) for g in guests], "events": []}
    session = frida.get_local_device().attach(args.pid)
    disconnected = threading.Event()
    session.on("detached", lambda *_: disconnected.set())
    payload = {k: getattr(args, k) for k in ("g_mem", "g_disp", "g_code_lo", "g_code_hi", "samples")}
    payload["only_types"] = [int(t, 0) for t in args.only_types.split(",") if t.strip()]
    script = session.create_script(JS.replace("PAYLOAD", json.dumps(payload)))

    def on_message(message, data):
        event = message.get("payload", message)
        result["events"].append(event)
        if message.get("type") == "error" or (isinstance(event, dict) and event.get("event") == "callback_error"):
            print(json.dumps(event), flush=True)

    script.on("message", on_message)
    started = time.perf_counter()
    try:
        script.load()
        api = script.exports_sync
        result["runtime"] = api.info()
        exe_path = Path(result["runtime"]["exe"])
        result["runtime_sha256"] = hashlib.file_digest(exe_path.open("rb"), "sha256").hexdigest()
        if result["runtime_sha256"] != args.expected_runtime_sha256.lower():
            raise RuntimeError("Runtime hash changed; rederive RVAs before overriding")
        print("READY", json.dumps(api.watch(specs)), flush=True)
        disconnected.wait(args.seconds)
        result["counts"] = None if disconnected.is_set() else api.counts()
        result["disconnected"] = disconnected.is_set()
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("SAVED", str(out), "elapsed", result["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
