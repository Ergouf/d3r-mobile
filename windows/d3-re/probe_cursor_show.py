"""Drive the runtime's native cursor and skill wheel directly for a visual check."""
from __future__ import annotations

import argparse

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports = {
  show(x, y, wheel) {
    const feed = new NativeFunction(base.add(0x1F97C0), 'void', ['float', 'float', 'int']);
    feed(x, y, 1);
    if (wheel) {
      const begin = new NativeFunction(base.add(0x1F97E0), 'void', []);
      begin();
      const moveFeed = new NativeFunction(base.add(0x1F97C0), 'void', ['float', 'float', 'int']);
      moveFeed(Math.min(1, x + 0.08), y, 1);
    }
    return {x, y, wheel};
  }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--x", type=float, default=0.5)
    ap.add_argument("--y", type=float, default=0.5)
    ap.add_argument("--wheel", action="store_true")
    args = ap.parse_args()
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        result = script.exports_sync.show(args.x, args.y, args.wheel)
    finally:
        session.detach()
    result["build"] = build
    print(result)


if __name__ == "__main__":
    main()
