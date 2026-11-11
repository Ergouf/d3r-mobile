"""Read one named UI text control from the live registry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

MASK64 = (1 << 64) - 1


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in data:
        h = ((h ^ c) * 0x100000001B3) & MASK64
    return h


JS = js_consts() + r"""
function q(a) { return gm.add(a).readU64().toNumber(); }
function u(a) { return gm.add(a).readU32(); }
rpc.exports.read = function(keyText) {
  const global = q(0x914f840), world = q(global + 0x10);
  const manager = q(world + 0xb80), map = q(manager);
  const mask = u(map), buckets = q(map + 0x10);
  let obj = 0;
  if (mask > 0x3ffff) throw new Error('bad registry');
  for (let b = 0; b <= mask && !obj; b++)
    for (let node = q(buckets + b * 8), guard = 0; node && guard++ < 2048; node = q(node))
      if (gm.add(node + 8).readU64().toString() === keyText) { obj = q(node + 0x10); break; }
  let text = null, cap = 0;
  if (obj) {
    const ptr = q(obj + 0x398); cap = u(obj + 0x3a0);
    if (ptr && cap > 0 && cap < 4096) {
      const bytes = gm.add(ptr).readByteArray(Math.min(cap, 1024));
      const arr = new Uint8Array(bytes);
      let end = 0;
      while (end < arr.length && arr[end] !== 0) end++;
      if (end > 0) text = gm.add(ptr).readUtf8String(end);
    }
  }
  return {obj, text, cap};
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--path", required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    key = str(fnv1a64(args.path.lower().encode()))
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.read(key)
    finally:
        session.detach()
    result.update({"path": args.path, "key": key, "build": build})
    print(json.dumps({"path": args.path, "obj": hex(result.get("obj") or 0),
                      "text": result.get("text"), "cap": result.get("cap"), "build": build["exe_sha256"][:8]},
                     ensure_ascii=True))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
