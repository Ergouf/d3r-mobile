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
    /* WalkGoal (native_world.c): 7 ints, then actor/serial/ticks/stuck, two
       WorldPos (16 bytes each), handle/controller/power/sno, entity, approach. */
    const goal = {
      active: u32(0), entity_goal: u32(4), submitted: u32(8),
      attack: u32(12), retries: u32(16),
      attack_retry: u32(20), stand_still: u32(24),
      actor: u32(28).toString(16), serial: u32(32), ticks: u32(36), stuck: u32(40),
      target: [f32(44), f32(48), f32(52)], target_place: u32(56),
      previous: [f32(60), f32(64), f32(68)],
      handle: u32(76).toString(16), controller: u32(80).toString(16), power: u32(84),
      sno: u32(88), entity: [f32(92), f32(96), f32(100)],
      entity_place: u32(104), approach: f32(108), assist_pending: u32(112)
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
