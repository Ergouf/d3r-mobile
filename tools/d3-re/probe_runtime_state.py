"""Read the native_world runtime state (enabled, UI block, current goal)."""
from __future__ import annotations

import argparse
import json

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {
  read() {
    const g = base.add(RVA.world_goal);
    const u32 = o => g.add(o).readU32();
    const f32 = o => g.add(o).readFloat();
    /* WalkGoal (native_world.c): 5 ints, then actor/serial/ticks/stuck, two
       WorldPos (16 bytes each), handle/controller/power/sno, entity, approach. */
    const goal = {
      active: u32(0), entity_goal: u32(4), submitted: u32(8),
      attack: u32(12), retries: u32(16),
      actor: u32(20).toString(16), serial: u32(24), ticks: u32(28), stuck: u32(32),
      target: [f32(36), f32(40), f32(44)], target_place: u32(48),
      previous: [f32(52), f32(56), f32(60)],
      handle: u32(68).toString(16), controller: u32(72).toString(16), power: u32(76),
      sno: u32(80), entity: [f32(84), f32(88), f32(92)],
      entity_place: u32(96), approach: f32(100), assist_pending: u32(104)
    };
    return {
      enabled: base.add(RVA.world_enabled).readU32(),
      ui_blocked: base.add(RVA.world_ui_blocked).readU32(),
      pointer_pending: base.add(RVA.world_pointer_pending).readU32(),
      serial: base.add(RVA.world_serial).readU32(),
      goal
    };
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    args = ap.parse_args()
    build = assert_installed()
    s = frida.get_local_device().attach(args.pid)
    try:
        j = s.create_script(JS)
        j.load()
        data = j.exports_sync.read()
    finally:
        s.detach()
    data["build"] = build
    print(json.dumps(data, indent=1))


if __name__ == "__main__":
    main()
