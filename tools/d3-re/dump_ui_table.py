#!/usr/bin/env python3
"""Dump D3's UI callback table through Frida.

The table is filled at startup by the main module's UI initializer. Entries are
24 bytes: {guest char* name; u32 djb2 hash; u32 padding; guest handler*}.

Usage:
  python tools/d3-re/dump_ui_table.py --json out/windows/kbm/b1/ui_table.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

DEFAULT_EXE = r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
DEFAULT_CWD = r"D:\Games\DiabloIII\01001B300B9BE000"
TABLE_OFFSET = 0x1876F20
ENTRY_SIZE = 0x18
MAX_ENTRIES = 1000

JS = r"""
try {
  const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
  const exp = mod.findExportByName('snx_module');
  const p = new NativeFunction(exp, 'pointer', [])();
  const mods = p.add(8).readPointer();
  let main = null;
  for (let i = 0; i < p.add(4).readU32(); i++) {
    const m = mods.add(i * 88);
    if (m.readPointer().readCString() === 'main') main = {base: m.add(8).readPointer(), size: m.add(16).readU64()};
  }
  if (!main) { send({error: 'main module missing'}); }
  else {
    let host = null;
    for (const r of Process.enumerateRanges('rw-')) if (r.size === main.size.toNumber()) { host = r.base; break; }
    if (!host) { send({error: 'host main view missing'}); }
    else {
      const table = host.add(TABLE_OFFSET);
      const entries = [];
      for (let i = 0; i < MAX_ENTRIES; i++) {
        const e = table.add(i * ENTRY_SIZE);
        const namep = e.readPointer();
        const hash = e.add(8).readU32();
        const handler = e.add(0x10).readPointer();
        if (namep.compare(main.base) < 0 || namep.compare(main.base.add(main.size)) >= 0) break;
        const noff = namep.sub(main.base).toUInt32();
        let name = null;
        try {
          const bytes = new Uint8Array(host.add(noff).readByteArray(160));
          let s = '';
          for (let k = 0; k < bytes.length && bytes[k] !== 0; k++) s += String.fromCharCode(bytes[k]);
          name = s;
        } catch (err) {}
        entries.push({i, name, hash, name_guest: namep.toString(), handler_guest: handler.toString(),
                      handler_offset: handler.sub(main.base).toUInt32()});
      }
      send({main_base: main.base.toString(), host_base: host.toString(), entries});
    }
  }
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--exe", default=DEFAULT_EXE)
    parser.add_argument("--cwd", default=DEFAULT_CWD)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--table-offset", type=lambda s: int(s, 0), default=TABLE_OFFSET)
    parser.add_argument("--max-entries", type=int, default=MAX_ENTRIES)
    parser.add_argument("--spawn-wait", type=float, default=10.0)
    parser.add_argument("--game-script", default=None, help="extra runtime --script= value for the spawned game")
    args = parser.parse_args()

    device = frida.get_local_device()
    pid = args.pid
    spawned = False
    if pid is None:
        argv = [args.exe]
        if args.game_script:
            argv.append(f"--script={args.game_script}")
            argv.append("--press_len=300")
        pid = device.spawn(argv, cwd=args.cwd)
        spawned = True
        device.resume(pid)
        time.sleep(args.spawn_wait)

    session = device.attach(pid)
    script = session.create_script(
        JS.replace("TABLE_OFFSET", hex(args.table_offset))
          .replace("ENTRY_SIZE", hex(ENTRY_SIZE))
          .replace("MAX_ENTRIES", str(args.max_entries))
    )
    result = []
    script.on("message", lambda message, data: result.append(message.get("payload", {})))
    script.load()
    time.sleep(0.5)
    session.detach()
    out = result[0] if result else {"error": "no message"}
    out["pid"] = pid
    out["spawned"] = spawned
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text[:4000])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.json} ({len(out.get('entries', []))} entries)")
    if spawned and not args.keep:
        device.kill(pid)


if __name__ == "__main__":
    main()
