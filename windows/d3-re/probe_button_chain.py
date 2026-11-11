"""Read-only: follow one real pad button from the device mask into the manager state.

The runtime's own sampler (`hid_update`) is driven with a button bit for a
short phase, the SDK copies it into the engine device object (+0x30), and the
input manager maps it into the per-player window.  This probe samples, at about
100 Hz, the device mask and the manager outputs so the reader can see which
field follows which bit; it writes only the runtime's pad1 state (the same
path the frontend uses) and restores it.

Phases (default): none -> ZL(0x100) -> none -> ZR(0x200) -> none.

Usage:
  python windows/d3-re/probe_button_chain.py --pid <pid> [--out out/windows/kbm/button-chain.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida

import version

JS = version.js_consts() + r"""
const hle = base.add(RVA.g_hle_ptr).readPointer();
const out = { host: null, samples: [], errors: [], phases: [], calls: 0 };
let mask = '0x0';
let phase = 'init';
const phaseLog = [];
function setMask(v, name) {
  mask = '0x' + v.toString(16);
  phase = name;
  phaseLog.push({ t: Date.now(), name, mask });
}
const hidHost = base.add(RVA.hid_update);
Interceptor.attach(hidHost, {
  onEnter() {
    out.calls++;
    hle.add(HLE.pad_buttons).writeU64(uint64(mask));
  }
});
let lastS = 0x9839FFC;
const mgrHost = resolveGuest(0x80FD4B0);
if (mgrHost) {
  Interceptor.attach(mgrHost, {
    onEnter(args) {
      try {
        const cpu = args[0];
        const lr = parseInt(cpu.add(30 * 8).readPointer().toString(), 16);
        const x0 = parseInt(cpu.add(0).readPointer().toString(), 16);
        out.mgr = out.mgr || {};
        const key = lr.toString(16) + ':' + x0.toString(16);
        out.mgr[key] = (out.mgr[key] || 0) + 1;
        if (lr === 0x82B93CC) lastS = x0;
      } catch (e) { out.mgrErr = e.message; }
    }
  });
}
function g32(g) { return gm.add(ptr(g)).readS32(); }
function g64(g) { return gm.add(ptr(g)).readU64().toNumber(); }
function safe(fn, d) { try { return fn(); } catch (e) { return d === undefined ? null : d; } }
function chain() {
  const A = safe(() => g64(0x914f840));
  const B = A ? safe(() => g64(A + 0x10)) : null;
  const P = B ? safe(() => g64(B + 0xbb0)) : null;
  return { A, B, P };
}
function player(s, i) {
  const start = s + i * 0x10C + 0x330;
  return { i, start,
           win: hexBytes(start, 0x70),
           m36c: safe(() => g32(start + 0x3C)),
           m370: safe(() => g32(start + 0x40)),
           m374: safe(() => g32(start + 0x44)),
           m39c: safe(() => g32(start + 0x6C)) };
}
function sample() {
  try {
    const c = chain();
    const s = lastS;               /* manager state (x0), captured at entry */
    const dev = 0x97CD7A8;
    const rec = {
      t: Date.now(), phase, mask,
      dev30: safe(() => gm.add(ptr(dev + 0x30)).readU64().toString()),
      dev40: safe(() => gm.add(ptr(dev + 0x40)).readU8()),
      dev10: safe(() => gm.add(ptr(dev + 0x10)).readU32()),
      dev04: safe(() => gm.add(ptr(dev + 4)).readU8()),
      s: s, chain: c,
      players: [0, 1, 2, 3].map(i => player(s, i)),
      p39c: c.P ? safe(() => g32(c.P + 0x39C)) : null,
      p3a0: c.P ? safe(() => g32(c.P + 0x3A0)) : null,
      p3a8: c.P ? safe(() => g32(c.P + 0x3A8)) : null
    };
    out.samples.push(rec);
  } catch (e) { if (out.errors.length < 5) out.errors.push(e.message); }
}
const timer = setInterval(sample, 20);
rpc.exports = {
  setMask, phaseLog: () => phaseLog,
  stop: () => { clearInterval(timer); hle.add(HLE.pad_buttons).writeU64(uint64('0x0')); return out; }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync
    plan = [("none0", 0x0, 0.6), ("ZL", 0x100, 0.8), ("none1", 0x0, 0.5),
            ("Plus", 0x400, 0.8), ("none2", 0x0, 0.5), ("A", 0x1, 0.8), ("none3", 0x0, 0.6)]
    for name, mask, seconds in plan:
        api.set_mask(mask, name)
        time.sleep(seconds)
    data = api.stop()
    data["phases"] = api.phase_log()
    session.detach()
    result = {"pid": args.pid, "phases": data.get("phases"), "calls": data.get("calls"),
              "errors": data.get("errors"), "samples": data.get("samples")}
    text = json.dumps(result, indent=2)
    print(text[:6000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
