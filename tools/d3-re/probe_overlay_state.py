"""Read the SCARLETNX overlay menu state and the native KBM bindings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import frida

from version import assert_installed, js_consts

NAMES = [
    "backend_kbm_key", "backend_kbm_action", "overlay_shown",
    "shown", "page", "focus", "top", "keyboard_capture", "keyboard_status",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    build = assert_installed()
    symbols = version_symbols()
    missing = [name for name in NAMES if name not in symbols]
    if missing:
        raise SystemExit(f"missing symbols: {missing}")
    rvas = {name: symbols[name] for name in NAMES}
    source = js_consts() + chr(10) + "const R =" + json.dumps(rvas) + r""";
rpc.exports.read = () => {
  const i32 = a => base.add(a).readS32();
  const key = new NativeFunction(base.add(R.backend_kbm_key), 'pointer', ['int']);
  const action = new NativeFunction(base.add(R.backend_kbm_action), 'pointer', ['int']);
  const shownFn = new NativeFunction(base.add(R.overlay_shown), 'int', []);
  const statusPtr = base.add(R.keyboard_status).readPointer();
  return {
    shown: shownFn(),
    shown_raw: i32(R.shown),
    page: i32(R.page),
    focus: i32(R.focus),
    top: i32(R.top),
    capture: i32(R.keyboard_capture),
    status: statusPtr.isNull() ? null : statusPtr.readUtf8String(),
    bindings: Array.from({length: 22}, (_, index) =>
      ({index, action: action(index).readUtf8String(), key: key(index).readUtf8String()}))
  };
};
"""
    session = frida.attach(args.pid)
    try:
        script = session.create_script(source)
        script.load()
        result = script.exports_sync.read()
    finally:
        session.detach()
    report = dict(build=build, pid=args.pid, **result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


def version_symbols():
    import version
    return version._symbol_table(version.EXE)


if __name__ == "__main__":
    main()
