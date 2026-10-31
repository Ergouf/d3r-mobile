#!/usr/bin/env python3
"""Dump the running game's guest code from g_mem (the runtime's real code).

The fixed ELF built from local/assets/exefs_update/main.nso0 does not match the
installed _code.dll's guest code (see docs/windows/KBM-RE-EVIDENCE.md 13.4).
This probe reads the main module's text and rodata straight out of the runtime's
flat guest memory, so disassembly is of the code the CPU actually runs.

Usage:
  python tools/d3-re/dump_runtime_code.py --pid 7904 --out out/windows/kbm/b2/runtime
"""
from __future__ import annotations

import argparse
import json
import os
import time

import frida

# g_mem is a global in the runtime executable; the offset is build-specific and
# printed by `llvm-nm scarletnx.exe | findstr " g_mem$"`.
G_MEM_OFFSET = 0x17aef20

JS = r"""
const EXE = '01001B300B9BE000.exe';
const G_MEM_OFFSET = PAYLOAD.gmem;
let gmem = null, main = null;
try {
  const exe = Process.enumerateModules().find(m => m.name.toLowerCase() === EXE.toLowerCase());
  if (!exe) throw new Error('runtime exe not found');
  gmem = exe.base.add(G_MEM_OFFSET).readPointer();
  const mod = Process.enumerateModules().find(m => m.name === '01001B300B9BE000_code.dll');
  const exp = mod.findExportByName('snx_module');
  const p = new NativeFunction(exp, 'pointer', [])();
  const mods = p.add(8).readPointer();
  for (let i = 0; i < p.add(4).readU32(); i++) {
    const m = mods.add(i * 88);
    if (m.readPointer().readCString() === 'main') {
      main = {
        base: m.add(8).readPointer().toString(),
        size: m.add(16).readU64().toString(),
        text_off: m.add(56).readU32(), text_size: m.add(60).readU32(),
        ro_off: m.add(64).readU32(), ro_size: m.add(68).readU32(),
        data_off: m.add(72).readU32(), data_size: m.add(76).readU32(),
        bss_size: m.add(80).readU32(),
      };
    }
  }
  rpc.exports = {
    info() { return {gmem: gmem.toString(), main}; },
    read(off, len) { return gmem.add(off).readByteArray(len); },
  };
  send({ready: true, gmem: gmem.toString(), main});
} catch (e) { send({ready: false, error: e.message}); }
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", default="out/windows/kbm/b2/runtime")
    ap.add_argument("--chunk", type=int, default=1 << 20)
    args = ap.parse_args()

    device = frida.get_local_device()
    session = device.attach(args.pid)
    script = session.create_script(JS.replace("PAYLOAD", json.dumps({"gmem": G_MEM_OFFSET})))
    ready: list[dict] = []
    script.on("message", lambda m, d: ready.append(m.get("payload", {})))
    script.load()
    for _ in range(50):
        if ready:
            break
        time.sleep(0.1)
    if not ready or not ready[0].get("ready"):
        raise SystemExit(f"probe failed: {ready}")
    info = ready[0]
    print(json.dumps(info, indent=2))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    base = int(info["main"]["base"], 16)
    for name, off_key, size_key in (("text", "text_off", "text_size"), ("rodata", "ro_off", "ro_size"),
                                    ("data", "data_off", "data_size")):
        off = int(info["main"][off_key])
        size = int(info["main"][size_key])
        if not size:
            continue
        path = f"{args.out}_{name}.bin"
        written = 0
        with open(path, "wb") as f:
            while written < size:
                n = min(args.chunk, size - written)
                buf = script.exports_sync.read(base + off + written, n)
                f.write(bytes(buf))
                written += n
        print(f"{name}: {written} bytes -> {path} (guest {base + off:#x})")
    with open(f"{args.out}_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    session.detach()


if __name__ == "__main__":
    main()
