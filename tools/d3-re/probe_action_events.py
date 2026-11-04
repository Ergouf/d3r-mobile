"""Compare two input paths against one business observable: the UI object registry.

Observable (dump_ui_objects.py chain, corrected one level):

    p1 = *(0x914f840); p2 = *(p1+0x10); p3 = *(p2+0xb80); map = *(p3)
    mask = u32(map); count = u32(map+4)

Phases: idle -> pad bit (control) -> idle -> logical-mask bit -> idle.
The logical bit is written into the engine input state (S + 0x36C) from a
timer; the pad bit goes through the runtime's own sampler.

Usage:
  python tools/d3-re/probe_action_events.py --pid <pid> --bit 0x1000 [--out ...]
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
const out = { hosts: {}, samples: [], errs: [] };
let padMask = '0x0', inj = 0, lastS = 0, phase = 'init';
function setPhase(n) { phase = n; out.samples.push({ t: Date.now(), phase: n, kind: 'phase' }); }
function setPad(v) { padMask = '0x' + v.toString(16); }
function setInj(v) { inj = v; }

Interceptor.attach(base.add(RVA.hid_update), {
  onEnter() { hle.add(HLE.pad_buttons).writeU64(uint64(padMask)); }
});
const mgrHost = resolveGuest(0x80FD4B0);
out.hosts.mgr = mgrHost ? mgrHost.toString() : null;
if (mgrHost) {
  Interceptor.attach(mgrHost, {
    onEnter(args) {
      const cpu = args[0];
      const lr = parseInt(cpu.add(30 * 8).readPointer().toString(), 16);
      if (lr === 0x82B93CC) lastS = parseInt(cpu.add(0).readPointer().toString(), 16);
    }
  });
}
setInterval(() => {
  if (!inj || !lastS) return;
  try {
    const p = lastS + 0x36C;
    const old = gm.add(ptr(p)).readU32();
    gm.add(ptr(p)).writeU32((old | inj) >>> 0);
  } catch (e) { if (out.errs.length < 5) out.errs.push('w:' + e.message); }
}, 4);

function g64(g) { return gm.add(ptr(g)).readU64().toNumber(); }
function registry() {
  const p1 = g64(0x914f840);
  const p2 = p1 ? g64(p1 + 0x10) : 0;
  const p3 = p2 ? g64(p2 + 0xB80) : 0;
  const map = p3 ? g64(p3) : 0;
  if (!map) return null;
  return { mask: gm.add(ptr(map)).readU32(), count: gm.add(ptr(map + 4)).readU32() };
}
const timer = setInterval(() => {
  try {
    out.samples.push({ t: Date.now(), phase, pad: padMask, inj, reg: registry(),
                       s36c: lastS ? gm.add(ptr(lastS + 0x36C)).readU32() : null });
  } catch (e) { if (out.errs.length < 5) out.errs.push('s:' + e.message); }
}, 20);
rpc.exports = {
  setPad, setInj, setPhase, hosts: () => out.hosts,
  stop: () => { clearInterval(timer); inj = 0; padMask = '0x0';
                hle.add(HLE.pad_buttons).writeU64(uint64('0x0')); return out; }
};
"""


def stats(samples, phase):
    rows = [s for s in samples if s.get("phase") == phase and s.get("reg")]
    counts = [r["reg"]["count"] for r in rows]
    masks = {r["reg"]["mask"] for r in rows}
    s36c = {r.get("s36c") for r in rows}
    return {"n": len(rows), "min": min(counts) if counts else None,
            "max": max(counts) if counts else None,
            "uniq": sorted(set(counts))[:8], "masks": sorted(masks)[:4],
            "s36c": sorted(v for v in s36c if v is not None)[:4]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--bit", type=lambda s: int(s, 0), default=0x1000)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync
    print("hosts", api.hosts())

    def hold(name: str, pad: int, inj: int, seconds: float) -> None:
        api.set_pad(pad); api.set_inj(inj); api.set_phase(name); time.sleep(seconds)

    hold("idle0", 0x0, 0, 0.8)
    hold("pad", args.bit, 0, 1.2)
    hold("idle1", 0x0, 0, 0.8)
    hold("mask", 0x0, args.bit, 1.2)
    hold("idle2", 0x0, 0, 0.8)
    data = api.stop()
    session.detach()
    for name in ("idle0", "pad", "idle1", "mask", "idle2"):
        print(name, stats(data["samples"], name))
    print("errors", data["errs"][:3])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"pid": args.pid, "bit": hex(args.bit), "hosts": data["hosts"],
                           "errors": data["errs"], "samples": data["samples"]}, indent=2)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
