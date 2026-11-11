"""Compare UI event dispatch for two input paths.

Path A: pad bit through the runtime sampler (existing, diagnostic control).
Path B: logical bit written into the engine input state (S + 0x36C).

For each phase the probe counts the widget OnEvent calls by event type, so a
business action shows up as new event types rather than as a guessed flag.
Read-only apart from the deliberate input writes.

Usage:
  python windows/d3-re/probe_ui_events.py --pid <pid> --bit 0x1000 --out out/windows/kbm/ui-events.json
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
const out = { host: null, calls: 0, errs: [], phases: [], types: {} };
let padMask = '0x0', inj = 0, lastS = 0, phase = 'init';
function reset() { out.types[phase] = out.types[phase] || {}; }
function setPhase(n) { phase = n; reset(); out.phases.push({ t: Date.now(), name: n }); }
function setPad(v) { padMask = '0x' + v.toString(16); }
function setInj(v) { inj = v; }

Interceptor.attach(base.add(RVA.hid_update), {
  onEnter() { hle.add(HLE.pad_buttons).writeU64(uint64(padMask)); }
});

const mgrHost = resolveGuest(0x80FD4B0);
out.host = mgrHost ? mgrHost.toString() : null;
if (mgrHost) {
  Interceptor.attach(mgrHost, {
    onEnter(args) {
      const cpu = args[0];
      const lr = parseInt(cpu.add(30 * 8).readPointer().toString(), 16);
      if (lr === 0x82B93CC) lastS = parseInt(cpu.add(0).readPointer().toString(), 16);
    }
  });
}
/* logical-mask writer, independent of the game thread */
const writer = setInterval(() => {
  if (!inj || !lastS) return;
  try {
    const p = lastS + 0x36C;
    const old = gm.add(ptr(p)).readU32();
    gm.add(ptr(p)).writeU32((old | inj) >>> 0);
  } catch (e) { if (out.errs.length < 5) out.errs.push('w:' + e.message); }
}, 4);

const evHost = resolveGuest(0x83BAD40);
const ev = { host: evHost ? evHost.toString() : null };
if (evHost) {
  Interceptor.attach(evHost, {
    onEnter(args) {
      out.calls++;
      try {
        const cpu = args[0];
        const x1 = cpu.add(8).readPointer();
        const type = x1.isNull() ? -1 : x1.readU32();
        const bucket = out.types[phase] = out.types[phase] || {};
        bucket[type] = (bucket[type] || 0) + 1;
      } catch (e) { if (out.errs.length < 5) out.errs.push('e:' + e.message); }
    }
  });
}
rpc.exports = {
  setPad, setInj, setPhase, ev: () => ev,
  stop: () => { clearInterval(writer); inj = 0; padMask = '0x0';
                hle.add(HLE.pad_buttons).writeU64(uint64('0x0')); return out; }
};
"""


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
    print("widget OnEvent:", api.ev())

    def hold(name: str, pad: int, inj: int, seconds: float) -> None:
        api.set_phase(name)
        api.set_pad(pad)
        api.set_inj(inj)
        time.sleep(seconds)

    hold("idle0", 0x0, 0, 0.8)
    hold("pad", args.bit, 0, 1.0)
    hold("idle1", 0x0, 0, 0.8)
    hold("mask", 0x0, args.bit, 1.0)
    hold("idle2", 0x0, 0, 0.8)
    data = api.stop()
    session.detach()

    print("phases:", [p["name"] for p in data.get("phases", [])])
    for name in ("idle0", "pad", "idle1", "mask", "idle2"):
        t = data.get("types", {}).get(name, {})
        print(f"{name:6s}", dict(sorted(t.items(), key=lambda kv: -kv[1])[:8]))
    print("calls", data.get("calls"), "errors", data.get("errs"))
    text = json.dumps(data, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
