#!/usr/bin/env python3
"""Observe the engine's own move submissions (read-only) to learn thread and arguments.

Hooks ``0x8828460`` (``w0``=actor handle, ``x1``=path, ``w2``=integer, ``s0``=float) and
``0x82B9230`` (frame update), records the guest thread, TPIDR/TPIDRRO, the arguments and the
path bytes for every call.  Pressing a real movement key makes the game submit its own move, so
the values recorded here are ground truth for the thread and the w2/s0 semantics.

Usage:
  python windows/d3-re/probe_move_submit.py --pid <pid> [--key w] [--hold-ms 1500]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

SUBMIT = 0x8828460
FRAME = 0x82B9230
WRAPPER = 0x8939970
SCRIPT = 0x88B98B0

JS = js_consts() + f"""
const SUBMIT = 0x{SUBMIT:x}, FRAME = 0x{FRAME:x};
const WRAPPER = 0x{WRAPPER:x}, SCRIPT = 0x{SCRIPT:x};
const V0 = 280;

function gp(a) {{ return gm.add(a); }}
function hexBytes(a, n) {{
  try {{ return Array.from(new Uint8Array(gp(a).readByteArray(n)), b => b.toString(16).padStart(2, '0')).join(''); }}
  catch (e) {{ return 'err:' + e.message; }}
}}
function f32(hex, i) {{
  const b = [];
  for (let k = 0; k < 4; k++) b.push(parseInt(hex.substr(i * 8 + k * 2, 2), 16));
  return new DataView(new Uint8Array(b).buffer).getFloat32(0, true);
}}
function tls(cpu) {{
  let tpidr = null, tpidrro = null;
  try {{ tpidr = cpu.add(800).readU64().toString(); }} catch (e) {{}}
  try {{ tpidrro = cpu.add(808).readU64().toString(); }} catch (e) {{}}
  return {{ tid: Process.getCurrentThreadId(), tpidr, tpidrro }};
}}

const out = {{ submits: [], frames: [], errors: [] }};

function hookSimple(pc, key) {{
  const host = resolveGuest(pc);
  if (!host) {{ out.errors.push(key + ' not resolvable'); return; }}
  Interceptor.attach(host, {{
    onEnter(args) {{
      const rec = out[key] || (out[key] = []);
      if (rec.length >= 100) return;
      try {{
        const cpu = args[0];
        const t = tls(cpu);
        t.actor = cpu.add(0).readPointer().toString();
        t.arg1 = cpu.add(8).readPointer().toString();
        t.arg2 = cpu.add(16).readPointer().toString();
        const v0 = cpu.add(V0).readByteArray(16);
        t.s0 = new DataView(v0).getFloat32(0, true);
        rec.push(t);
      }} catch (e) {{ if (out.errors.length < 8) out.errors.push(key + ': ' + e.message); }}
    }}
  }});
}}
hookSimple(WRAPPER, 'wrapper');
hookSimple(SCRIPT, 'script');

const submitHost = resolveGuest(SUBMIT);
if (submitHost) {{
  Interceptor.attach(submitHost, {{
    onEnter(args) {{
      if (out.submits.length >= 200) return;
      try {{
        const cpu = args[0];
        const rec = tls(cpu);
        rec.actor = cpu.add(0).readPointer().toString();
        rec.path = cpu.add(8).readPointer().toString();
        rec.w2 = cpu.add(16).readU32();
        const v0 = cpu.add(V0).readByteArray(16);
        rec.s0 = new DataView(v0).getFloat32(0, true);
        rec.path_hex = hexBytes(parseInt(rec.path, 16), 0x20);
        rec.path_type = gp(parseInt(rec.path, 16)).readU32();
        rec.path_id = gp(parseInt(rec.path, 16) + 4).readU32();
        rec.pos = [f32(rec.path_hex, 1), f32(rec.path_hex, 2), f32(rec.path_hex, 3)];
        out.submits.push(rec);
      }} catch (e) {{ if (out.errors.length < 8) out.errors.push('submit: ' + e.message); }}
    }}
  }});
}} else out.errors.push('submit not resolvable');

const frameHost = resolveGuest(FRAME);
if (frameHost) {{
  Interceptor.attach(frameHost, {{
    onEnter(args) {{
      if (out.frames.length >= 40) return;
      try {{
        const rec = tls(args[0]);
        rec.cpu = args[0].toString();
        out.frames.push(rec);
      }} catch (e) {{ if (out.errors.length < 8) out.errors.push('frame: ' + e.message); }}
    }}
  }});
}} else out.errors.push('frame not resolvable');

rpc.exports = {{ data() {{ return out; }} }};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--key", default="w")
    ap.add_argument("--hold-ms", type=int, default=1500)
    ap.add_argument("--wait", type=float, default=2.0)
    ap.add_argument("--out", type=Path, default=Path("out/windows/kbm/move-submit.json"))
    args = ap.parse_args()

    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.on("message", lambda m, d: print("js:", m.get("payload", m), flush=True))
    script.load()
    api = script.exports_sync
    try:
        time.sleep(0.5)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        "windows/tools/Post-GameInput.ps1", "-Key", args.key,
                        "-HoldMs", str(args.hold_ms), "-ProcessId", str(args.pid)], check=True)
        time.sleep(args.wait)
        data = api.data()
    finally:
        session.detach()
    print("submits:", len(data.get("submits", [])))
    for rec in data.get("submits", [])[:12]:
        print("  ", {k: rec.get(k) for k in ("tid", "tpidrro", "actor", "w2", "s0", "path_type", "path_id", "pos")})
    print("wrapper calls:", len(data.get("wrapper", [])), "script calls:", len(data.get("script", [])))
    for key in ("wrapper", "script"):
        for rec in data.get(key, [])[:4]:
            print("  ", key, {k: rec.get(k) for k in ("tid", "tpidrro", "actor", "arg1", "arg2", "s0")})
    tids = {}
    for rec in data.get("frames", []):
        tids[rec["tid"]] = tids.get(rec["tid"], 0) + 1
    print("frame tids:", tids)
    print("errors:", data.get("errors"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
