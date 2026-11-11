"""Diagnostic one-stick pulse while inventory is open; no mouse completion claim."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts


JS = js_consts() + r"""
const hle=base.add(RVA.g_hle_ptr).readPointer();
const pad=hle.add(HLE.pad_buttons);
let axis=0, value=0, otherAxis=0, otherValue=0;
const hook=Interceptor.attach(base.add(RVA.hid_update), {onEnter(){
  if(axis) pad.add(axis).writeS32(value);
  if(otherAxis) pad.add(otherAxis).writeS32(otherValue);
}});
function q(a){return gm.add(a).readU64().toNumber();}
function s(a){return gm.add(a).readS32();}
rpc.exports={
  pulse(off,v,otherOff,otherV){axis=off;value=v;otherAxis=otherOff;otherValue=otherV;return true;},
  release(){if(axis)pad.add(axis).writeS32(0);if(otherAxis)pad.add(otherAxis).writeS32(0);
    axis=0;value=0;otherAxis=0;otherValue=0;return true;},
  state(){
    const ring=0x15d47f700, owner=q(q(0x9157f58));
    return {ring, selected:q(ring+0x538), selected2:q(ring+0x540),
      owner, controller:[0x138,0x140,0x148].map(o=>q(owner+o)),
      mode:[0x150,0x154,0x1394].map(o=>s(owner+o)),
      padAxes:[8,12,16,20].map(o=>pad.add(o).readS32())};
  },
  stop(){hook.detach();if(axis)pad.add(axis).writeS32(0);if(otherAxis)pad.add(otherAxis).writeS32(0);
    axis=0;otherAxis=0;return true;}
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, default=6032)
    ap.add_argument("--axis", choices=("lx", "ly", "rx", "ry"), required=True)
    ap.add_argument("--value", type=int, required=True)
    ap.add_argument("--other-axis", choices=("lx", "ly", "rx", "ry"))
    ap.add_argument("--other-value", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=0.25)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if not -32767 <= args.value <= 32767 or not -32767 <= args.other_value <= 32767:
        ap.error("stick values must be -32767..32767")
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        api = script.exports_sync
        before = api.state()
        offsets = {"lx": 8, "ly": 12, "rx": 16, "ry": 20}
        api.pulse(offsets[args.axis], args.value,
                  offsets[args.other_axis] if args.other_axis else 0, args.other_value)
        time.sleep(args.seconds)
        during = api.state()
        api.release()
        time.sleep(0.2)
        after = api.state()
        api.stop()
    finally:
        session.detach()
    result = {"axis": args.axis, "value": args.value,
              "before": before, "during": during, "after": after}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
