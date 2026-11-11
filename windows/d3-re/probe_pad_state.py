#!/usr/bin/env python3
"""Sample the engine's player-1 Npad device object to prove a key path writes no Npad input.

The engine's input manager keeps the pad device at guest 0x97CD7A8 (verified 2026-11-01): +0x18/+0x1c and
+0x20/+0x24 are the stick axes, +0x30 the button mask the manager reads, +0x40 a status byte. A native action
must leave all of them at zero.

A zero sample only proves this Npad device was not written through the path being watched; it does not exclude
other input paths (keyboard/mouse, HID, touch, or a different pad slot). Pair it with the event/action logs.

Usage:
  python windows/d3-re/probe_pad_state.py --pid <pid> --seconds 8
"""
from __future__ import annotations

import argparse
import time

import frida

from version import assert_installed, js_consts

PAD_DEVICE = 0x97CD7A8


def build_js(seconds: float) -> str:
    return (
        js_consts()
        + f"""
const dev = ptr(0x{PAD_DEVICE:x});
const t0 = Date.now();
const seen = {{}};
let maxMask = 0, maxStatus = 0, maxStick = 0;
const timer = setInterval(() => {{
  try {{
    const mask = gm.add(dev).add(0x30).readU64();
    const status = gm.add(dev).add(0x40).readU32();
    const sticks = [0x18, 0x1c, 0x20, 0x24].map(o => gm.add(dev).add(o).readS32());
    const stickMax = sticks.reduce((a, b) => Math.max(a, Math.abs(b)), 0);
    if (mask.low) {{ maxMask |= mask.low; seen['mask:' + mask.toString(16)] = (seen['mask:' + mask.toString(16)] || 0) + 1; }}
    if (status) {{ maxStatus |= status; }}
    if (stickMax) {{ maxStick = Math.max(maxStick, stickMax); }}
  }} catch (e) {{ seen['error:' + e.message] = 1; }}
  if (Date.now() - t0 > {int(seconds * 1000)}) {{
    clearInterval(timer);
    send({{ done: true, seconds: {seconds}, maxMask, maxStatus, maxStick, seen }});
  }}
}}, 10);
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=8.0)
    args = ap.parse_args()
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(build_js(args.seconds))
    done = {"v": False}

    def on_message(message, _data):
        payload = message.get("payload", message)
        print(payload, flush=True)
        if isinstance(payload, dict) and payload.get("done"):
            done["v"] = True

    script.on("message", on_message)
    script.load()
    for _ in range(int(args.seconds * 20) + 60):
        if done["v"]:
            break
        time.sleep(0.1)
    session.detach()


if __name__ == "__main__":
    main()
