#!/usr/bin/env python3
"""Read D3's guest module map and known NSO strings through Frida.

B0 acceptance probe: it proves the Frida -> runtime -> guest-address path before
any game function is called. It never writes game memory and can spawn a
throwaway process or attach to a running one.

The runtime maps guest memory in host views. `snx_module` gives the guest base;
the host view is found by its exact main-module size, then the known NSO strings
are located by byte scan. That offset is the guest offset.
"""
from __future__ import annotations

import argparse
import json
import time

import frida

DEFAULT_EXE = r"D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
DEFAULT_CWD = r"D:\Games\DiabloIII\01001B300B9BE000"

KNOWN = [
    "LeftClickToMove",
    "RightClickAttack",
    "UseCommandClickAsRightClick",
    "UI_HUD_ClickPredicate",
    "ControlScheme",
    "ActionBinding",
]

READ_JS = r"""
try {
  const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
  if (!mod) { send({error: 'game code module not loaded'}); }
  else {
    const exp = mod.findExportByName('snx_module');
    if (!exp) { send({error: 'snx_module export missing'}); }
    else {
      const p = new NativeFunction(exp, 'pointer', [])();
      const n = p.add(4).readU32();
      const mods = p.add(8).readPointer();
      const out = {snx_module: p.toString(), abi: p.readU32(), modules: [], strings: {}};
      let main = null;
      for (let i = 0; i < n; i++) {
        const m = mods.add(i * 88);
        const item = {
          name: m.readPointer().readCString(),
          base: m.add(8).readPointer().toString(),
          size: m.add(16).readU64().toString(),
          text_off: m.add(56).readU32(), text_size: m.add(60).readU32(),
          ro_off: m.add(64).readU32(), ro_size: m.add(68).readU32(),
          data_off: m.add(72).readU32(), data_size: m.add(76).readU32()
        };
        out.modules.push(item);
        if (item.name === 'main') main = {base: m.add(8).readPointer(), size: m.add(16).readU64()};
      }
      if (!main) { out.error = 'main module missing'; send(out); }
      else {
        let host = null;
        for (const r of Process.enumerateRanges('rw-')) {
          if (r.size === main.size.toNumber()) { host = r.base; break; }
        }
        out.main_guest_base = main.base.toString();
        out.main_host_base = host ? host.toString() : null;
        if (host) {
          for (const name of PAYLOAD) {
            const hex = name.split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join('');
            const hits = Memory.scanSync(host, main.size.toNumber(), hex);
            if (hits.length) {
              const h = hits[0];
              const off = h.address.sub(host).toUInt32();
              let value = null;
              try {
                const bytes = new Uint8Array(h.address.readByteArray(96));
                let s = '';
                for (let i = 0; i < bytes.length && bytes[i] !== 0; i++) s += String.fromCharCode(bytes[i]);
                value = s;
              } catch (e) { value = null; }
              out.strings[name] = {
                host_address: h.address.toString(),
                guest_address: main.base.add(off).toString(),
                offset: off,
                value
              };
            } else {
              out.strings[name] = {error: 'not found'};
            }
          }
        }
        send(out);
      }
    }
  }
} catch (e) { send({error: e.message, stack: e.stack}); }
"""


def wait_for_module(device: frida.core.Device, pid: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            session = device.attach(pid)
            script = session.create_script(r"""
              send({ok: Process.enumerateModules().some(m => m.name === '01001B300B9BE000_code.dll')});
            """)
            result = []
            script.on("message", lambda message, data: result.append(message.get("payload", {})))
            script.load()
            time.sleep(0.2)
            session.detach()
            if result and result[0].get("ok"):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="attach to this pid instead of spawning")
    parser.add_argument("--exe", default=DEFAULT_EXE)
    parser.add_argument("--cwd", default=DEFAULT_CWD)
    parser.add_argument("--keep", action="store_true", help="leave a spawned process running")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    device = frida.get_local_device()
    pid = args.pid
    spawned = False
    if pid is None:
        pid = device.spawn([args.exe], cwd=args.cwd)
        spawned = True
        device.resume(pid)
        if not wait_for_module(device, pid):
            device.kill(pid)
            raise SystemExit("game code module did not load")

    session = device.attach(pid)
    script = session.create_script(READ_JS.replace("PAYLOAD", json.dumps(KNOWN)))
    result: list[dict] = []
    script.on("message", lambda message, data: result.append(message.get("payload", {})))
    script.load()
    time.sleep(0.4)
    session.detach()
    out = result[0] if result else {"error": "no message"}
    out["pid"] = pid
    out["spawned"] = spawned
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else out)
    if spawned and not args.keep:
        device.kill(pid)


if __name__ == "__main__":
    main()
