"""Read the overlay's skill-wheel key labels straight from the built exe's statics."""
from __future__ import annotations

import argparse
import json

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {read(base_rva) {
  const p = base.add(base_rva);
  const out = [];
  for (let i = 0; i < 6; i++) {
    try {
      const bytes = new Uint8Array(p.add(i * 24).readByteArray(24));
      let n = bytes.indexOf(0);
      if (n < 0) n = 24;
      out.push(Array.from(bytes.slice(0, n), b => String.fromCharCode(b)).join(''));
    } catch (e) { out.push('err:' + e.message); }
  }
  return out;
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--rva", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    build = assert_installed()
    s = frida.get_local_device().attach(args.pid)
    try:
        j = s.create_script(JS)
        j.load()
        labels = j.exports_sync.read(args.rva)
    finally:
        s.detach()
    print(json.dumps({"build": build, "labels": labels}, indent=1))


if __name__ == "__main__":
    main()
