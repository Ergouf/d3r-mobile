"""Business-action probe: push one logical bit into the engine input state.

The input manager (guest 0x80FD4B0) derives, per player, a logical action mask
at S + i*0x10C + 0x36C (S = entry x0).  This probe ORs one bit into player 0's
mask right after the manager returns, i.e. on the game's own thread and frame
phase, and watches the UI object registry entry count

    B = *(*(0x914f840) + 0x10); M = *(B + 0xb80); count = u32(M + 4)

as an objective effect.  The pad path through the existing runtime sampler is
used as the control.

Phases: idle -> mask bit -> idle -> pad bit (control) -> idle.

Usage:
  python windows/d3-re/probe_mask_inject.py --pid <pid> --bit 0x1000 --out out/windows/kbm/mask-inject.json
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
const out = { mgr: null, calls: 0, errs: [], samples: [], phases: [] };
let padMask = '0x0';
let inj = 0;              /* logical bit injected after the manager returns */
let lastS = 0;
let phase = 'init';
function setPhase(name) { phase = name; out.phases.push({ t: Date.now(), name }); }
function setPad(v) { padMask = '0x' + v.toString(16); }
function setInj(v) { inj = v; }

Interceptor.attach(base.add(RVA.hid_update), {
  onEnter() { hle.add(HLE.pad_buttons).writeU64(uint64(padMask)); }
});

const mgrHost = resolveGuest(0x80FD4B0);
if (mgrHost) {
  Interceptor.attach(mgrHost, {
    onEnter(args) {
      out.calls++;
      lastS = parseInt(args[0].add(0).readPointer().toString(), 16);
    },
    onLeave() {
      if (!inj || !lastS) return;
      try {
        const p = lastS + 0x36C;
        const old = gm.add(ptr(p)).readU32();
        gm.add(ptr(p)).writeU32((old | inj) >>> 0);
      } catch (e) { if (out.errs.length < 5) out.errs.push(e.message); }
    }
  });
  out.mgr = mgrHost.toString();
}
function g64(g) { return gm.add(ptr(g)).readU64().toNumber(); }
function registryCount() {
  const A = g64(0x914f840);
  if (!A) return null;
  const B = g64(A + 0x10);
  if (!B) return null;
  const M = g64(B + 0xB80);
  if (!M) return null;
  return { map: M, mask: gm.add(ptr(M)).readU32(), count: gm.add(ptr(M + 4)).readU32() };
}
function sample() {
  try {
    out.samples.push({ t: Date.now(), phase, pad: padMask, inj,
                       reg: registryCount(),
                       s36c: lastS ? gm.add(ptr(lastS + 0x36C)).readU32() : null });
  } catch (e) { if (out.errs.length < 5) out.errs.push(e.message); }
}
const timer = setInterval(sample, 20);
rpc.exports = {
  setPad, setInj, setPhase,
  stop: () => { clearInterval(timer); inj = 0; padMask = '0x0';
                hle.add(HLE.pad_buttons).writeU64(uint64('0x0')); return out; }
};
"""


def counts(samples, phase):
    return [s["reg"]["count"] for s in samples if s["phase"] == phase and s["reg"]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--bit", type=lambda s: int(s, 0), default=0x1000, help="logical bit to inject")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync

    def hold(name: str, pad: int, inj: int, seconds: float) -> None:
        api.set_phase(name)
        api.set_pad(pad)
        api.set_inj(inj)
        time.sleep(seconds)

    hold("idle0", 0x0, 0, 0.7)
    hold("mask", 0x0, args.bit, 0.7)
    hold("idle1", 0x0, 0, 0.7)
    hold("pad", args.bit, 0, 1.2)      # control: same bit through the pad device path
    hold("idle2", 0x0, 0, 0.7)
    data = api.stop()
    session.detach()

    result = {"pid": args.pid, "bit": hex(args.bit), "mgr": data.get("mgr"),
              "calls": data.get("calls"), "errors": data.get("errs"),
              "phases": data.get("phases"), "samples": data.get("samples")}
    for name in ("idle0", "mask", "idle1", "pad", "idle2"):
        vals = counts(result["samples"], name)
        print(f"{name:6s} n={len(vals):3d} min={min(vals) if vals else None} "
              f"max={max(vals) if vals else None} uniq={sorted(set(vals))[:6]}")
    text = json.dumps(result, indent=2)
    print(text[:1500])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
