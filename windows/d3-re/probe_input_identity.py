"""Read-only identity probe for the engine input manager and its consumer.

Hooks the input-manager entry (guest 0x80FD4B0) and records, on the first few
frames, the guest x0 (S) and x24 the caller passes (x0 == x24 + 4), then walks
the consumer chain

    A = *(0x914f840); B = *(A + 0x10); P = *(B + 0xbb0)

and reports the numeric relations between S, x24, B and P plus the raw bytes of
each player window (S + i*0x10C + 0x330 .. + 0x3A0) and of P.  Nothing is
written: this settles object identity before any tracing or call bridge.

Usage:
  python windows/d3-re/probe_input_identity.py --pid <pid> [--out out/windows/kbm/input-identity.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida

import version

JS = version.js_consts() + r"""
const MANAGER = 0x80FD4B0;
const out = { host: null, calls: 0, samples: [], errors: [], chain: null };
const host = resolveGuest(MANAGER);
out.host = host ? host.toString() : null;

function g64(g) { return gm.add(ptr(g)).readU64().toNumber(); }
function g32(g) { return gm.add(ptr(g)).readS32(); }

function readChain() {
  const A = g64(0x914f840);
  const B = A ? g64(A + 0x10) : 0;
  const P = B ? g64(B + 0xbb0) : 0;
  return { A, B, P, p39c: P ? g32(P + 0x39C) : null, p3a8: P ? g32(P + 0x3A8) : null };
}

function window(s) {
  if (!s) return null;
  const players = [];
  for (let i = 0; i < 4; i++) {
    const start = s + i * 0x10C + 0x330;
    players.push({ i, start, bytes: hexBytes(start, 0x70) });
  }
  return { head: hexBytes(s, 0x80), players };
}

if (host) {
  Interceptor.attach(host, {
    onEnter(args) {
      out.calls++;
      if (out.samples.length >= 3) return;
      try {
        if (!out.chain) out.chain = readChain();
        const cpu = args[0];
        const reg = n => cpu.add(n * 8).readPointer();
        const s = parseInt(reg(0).toString(), 16);
        const x24 = parseInt(reg(24).toString(), 16);
        const lr = parseInt(reg(30).toString(), 16);
        const rec = {
          s: s, x24: x24, lr: lr,
          s_eq_x24_plus4: s === x24 + 4,
          chain: out.chain,
          rel: {
            s_minus_p: out.chain.P ? s - out.chain.P : null,
            x24_minus_p: out.chain.P ? x24 - out.chain.P : null,
            s_minus_b: out.chain.B ? s - out.chain.B : null,
            s_eq_p: s === out.chain.P,
            p_in_s: out.chain.P >= s && out.chain.P < s + 0x2000,
            s_in_p: s >= out.chain.P && s < out.chain.P + 0x2000
          },
          sBytes: window(s),
          x24Bytes: window(x24),
          pBytes: out.chain.P ? { head: hexBytes(out.chain.P, 0x80),
                                  players: [0, 1, 2, 3].map(i => ({
                                    i, start: out.chain.P + i * 0x10C + 0x330,
                                    bytes: hexBytes(out.chain.P + i * 0x10C + 0x330, 0x70) })) } : null,
          x24Head: x24 ? hexBytes(x24, 0x20) : null
        };
        out.samples.push(rec);
      } catch (e) { if (out.errors.length < 5) out.errors.push(e.message); }
    }
  });
}
rpc.exports = { data: () => out, chain: readChain };
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--seconds", type=float, default=1.5)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    time.sleep(args.seconds)
    data = script.exports_sync.data()
    session.detach()
    text = json.dumps(data, indent=2)
    print(text[:8000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
