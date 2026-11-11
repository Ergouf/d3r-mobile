#!/usr/bin/env python3
"""Dump every key in the live UI object registry (name hashes only)."""
from __future__ import annotations

import json
import sys
import time

import frida

JS = r"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase().startsWith('01001b300b9be000.exe'));
const gmem = exe.base.add(0x17AEF20).readPointer();
function u64(a) { return Number(gmem.add(a).readU64()); }
function u32(a) { return gmem.add(a).readU32(); }
try {
  const p1 = u64(0x914f840);
  const p2 = u64(p1 + 0x10);
  const p3 = u64(p2 + 0xb80);
  const map = u64(p3);
  const mask = u32(map), count = u32(map + 4), buckets = u64(map + 0x10);
  send({event: 'header', mask, count, buckets});
  let batch = [];
  let total = 0;
  for (let b = 0; b <= mask; b++) {
    let node = u64(buckets + b * 8);
    let guard = 0;
    while (node && guard++ < 1000) {
      const key = gmem.add(node + 8).readU64();
      batch.push(key.toString());
      total++;
      if (batch.length >= 500) { send({event: 'batch', keys: batch}); batch = []; }
      node = u64(node);
    }
  }
  if (batch.length) send({event: 'batch', keys: batch});
  send({event: 'done', total});
} catch (e) { send({event: 'error', error: e.message, stack: e.stack}); }
"""


def main() -> None:
    pid = int(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else None
    session = frida.get_local_device().attach(pid)
    script = session.create_script(JS)
    keys: list[str] = []
    header = None
    done = False

    def on_message(message, data):
        nonlocal header, done
        p = message.get("payload", {})
        if p.get("event") == "header":
            header = p
            print(p, flush=True)
        elif p.get("event") == "batch":
            keys.extend(p["keys"])
            print(f"batch {len(keys)}", flush=True)
        elif p.get("event") == "done":
            print(p, flush=True)
            done = True
        else:
            print(p, flush=True)

    script.on("message", on_message)
    script.load()
    for _ in range(600):
        if done:
            break
        time.sleep(0.1)
    print(f"collected {len(keys)}", flush=True)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"header": header, "keys": keys}, f)
    session.detach()


if __name__ == "__main__":
    main()
