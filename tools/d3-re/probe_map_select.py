"""Select a waypoint-map row through the same guest calls native_ui.c uses.

The mouse picker in native_ui.c resolves the nearest row of the live
waypoint-map state (0x9154E30) and then calls 0x800F9F0 / 0x823EF60 /
0x8170BD0 / 0x81C0B80.  Rows whose map icon sits under the footer bar cannot
be clicked with the mouse, so this probe calls the same sequence for a given
row index and leaves the teleport footer to the normal UI click.

Usage: python tools/d3-re/probe_map_select.py --pid <pid> --row 17 --out ...
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_guest_call as bridge
from version import assert_installed

EXTENSION = r"""
function g32(a) { return gp(a).readU32(); }
function g64(a) { return gp(a).readU64().toNumber(); }
function hx(a) { return '0x' + a.toString(16); }
function mapSelect(cpu, req) {
  const state = g64(0x9154E30);
  const out = {ok: false, state: hx(state)};
  if (!state) return out;
  const data = g64(state + 0x28), count = g32(state + 0x30), player = g32(state + 0x20);
  out.count = count; out.player = player; out.data = hx(data);
  if (!data || !count || count > 256 || player !== 0) return out;
  if (req.row < 0 || req.row >= count) { out.error = 'row out of range'; return out; }
  const rows = [];
  for (let i = 0; i < count; i++) {
    const row = data + i * 24;
    rows.push({index: i, x: gp(row).readFloat(), y: gp(row + 4).readFloat(),
               id: g32(row + 8), key: g64(row + 16)});
  }
  out.rows = rows;
  const pick = callGuest(cpu, 0x800F9F0, [], null, null);
  out.pick = {ret: pick.ret | 0, returned: pick.returned, pc: pick.pc};
  gp(state + 0x44).writeU32(req.row);
  gp(state + 0x50).writeU32(pick.ret | 0);
  gp(state + 0x48).writeU32(1);
  const sel = callGuest(cpu, 0x823EF60, [req.row], null, null);
  out.select = {ret: sel.ret | 0, returned: sel.returned, pc: sel.pc};
  const dirty = callGuest(cpu, 0x8170BD0, [], null, null);
  out.dirty = {ret: dirty.ret | 0, returned: dirty.returned, pc: dirty.pc};
  if (dirty.ret) {
    const refresh = callGuest(cpu, 0x81C0B80, [dirty.ret, 1], null, null);
    out.refresh = {ret: refresh.ret | 0, returned: refresh.returned, pc: refresh.pc};
  }
  out.ok = true;
  return out;
}
"""


def build_js(context: int) -> str:
    js = bridge.JS.replace("__CONTEXT__", hex(context)).replace("__FRAME__", "0x80FC310")
    js = js.replace("__AFTER__", "false").replace("__EVENT__", "null")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
                      "if (req.mode === 'map_select') { result = mapSelect(cpu, req); } "
                      "else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=0x150030E60)
    ap.add_argument("--row", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    from session_driver import _process_identity
    identity = _process_identity(args.pid)
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe" for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is no longer running")
    session = device.attach(args.pid)
    try:
        script = session.create_script(build_js(args.context))
        script.on("message", lambda m, d: print(m, flush=True) if m.get("type") == "error" else None)
        script.load()
        req = {"mode": "map_select", "row": args.row}
        script.exports_sync.arm(req)
        deadline = time.monotonic() + 10
        data = {}
        while time.monotonic() < deadline:
            data = script.exports_sync.result()
            if data.get("result"):
                break
            time.sleep(0.1)
    finally:
        session.detach()
    data["build"] = build
    data["identity"] = identity
    data["req"] = req
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    result = data.get("result") or {}
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    for row in result.get("rows", []):
        print(f'row {row["index"]:>2} x={row["x"]:7.1f} y={row["y"]:7.1f} id={row["id"]}')


if __name__ == "__main__":
    main()
