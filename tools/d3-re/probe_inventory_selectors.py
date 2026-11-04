"""Read the live inventory controller's embedded selection objects. No writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts


JS = js_consts() + r"""
function q(a) { return gm.add(a).readU64().toNumber(); }
function u(a) { return gm.add(a).readU32(); }
function s(a) { return gm.add(a).readS32(); }
rpc.exports = { read() {
  const slot = q(0x9157f58), owner = q(slot);
  const offsets = [0xcd8,0xd60,0xde8,0xe70,0xee8,0xf60,0xfd8,
                   0x1068,0x10d8,0x1100,0x1198,0x1200];
  const selections = offsets.map(off => {
    const obj = owner + off, vt = q(obj);
    return {off,obj,vt,parent:q(obj+8),nameRef:q(obj+0x10),
      selected:s(obj+0x48),alternate:s(obj+0x4c),
      mode:s(obj+0x70),enabled:u(obj+0x18),
      method30:q(vt+0x30),method38:q(vt+0x38),
      method48:q(vt+0x48),method50:q(vt+0x50)};
  });
  const state = {};
  for (const off of [0x138,0x140,0x148,0x150,0x154,0x200,0x204,0x208,
                     0x20c,0x210,0x1388,0x138c,
                     0x1390,0x1394,0x1398,0x139c,0x13a0,0x13a4])
    state['0x'+off.toString(16)] = off < 0x150 ? q(owner+off) : s(owner+off);
  return {owner, ring:q(q(0x9157f58)+0x10), state, selections};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, default=6032)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.read()
    finally:
        session.detach()
    result["build"] = build
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("owner", hex(result["owner"]), "state", result["state"])
    for row in result["selections"]:
        print("+%04x vt=%#x selected=%d alt=%d mode=%d method30=%#x method48=%#x method50=%#x" %
              (row["off"], row["vt"], row["selected"], row["alternate"], row["mode"],
               row["method30"], row["method48"], row["method50"]))


if __name__ == "__main__":
    main()
