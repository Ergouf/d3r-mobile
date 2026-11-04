#!/usr/bin/env python3
"""Read words around candidate position triples found by probe_player_scan.py.

For each candidate address A (a float x of an x/y/z triple), prints the u32 at A-0x60 (entity id
candidate), the u32 at A-4, and A+0x40 (the +0xA0 field 0x847CEA0 also copies).

Usage:
  python tools/d3-re/probe_entity_around.py --pid <pid> 0x09804a28 0x097e3618
"""
from __future__ import annotations

import argparse
import time

import frida

from version import assert_installed, js_consts


def build_js(addrs: list[int]) -> str:
    return (
        js_consts()
        + f"""
const ADDRS = [{",".join("0x%x" % a for a in addrs)}];
for (const a of ADDRS) {{
  const base = a - 0x60;
  const out = {{ addr: a.toString(16), base: base.toString(16) }};
  try {{ out.id_at_base = gm.add(base).readU32(); }} catch (e) {{ out.id_at_base = 'err'; }}
  try {{ out.prev = gm.add(a - 4).readU32(); }} catch (e) {{ out.prev = 'err'; }}
  try {{ out.f = [0, 4, 8, 0x40].map(o => gm.add(a + o).readFloat()); }} catch (e) {{ out.f = 'err'; }}
  try {{ out.words = Array.from(new Uint32Array(gm.add(base).readByteArray(0x20))); }} catch (e) {{ out.words = 'err'; }}
  send(out);
}}
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("addrs", nargs="+", type=lambda s: int(s, 0))
    args = ap.parse_args()
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(build_js(args.addrs))
    script.on("message", lambda m, d: print(m.get("payload", m), flush=True))
    script.load()
    time.sleep(1.5)
    session.detach()


if __name__ == "__main__":
    main()
