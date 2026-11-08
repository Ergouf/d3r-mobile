"""Read runtime keyboard bindings through exported, read-only getters."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import frida
import session_driver
import version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build = version.assert_installed()
    identity = session_driver._process_identity(args.pid)
    symbols = version._symbol_table(version.EXE)
    names = ['backend_kbm_key', 'backend_kbm_action', 'overlay_shown']
    addresses = {name: symbols[name] for name in names}
    source = version.js_consts() + chr(10) + 'const getterRvas=' + json.dumps(addresses) + r''';
rpc.exports.read = () => {
  const key = new NativeFunction(base.add(getterRvas.backend_kbm_key), 'pointer', ['int']);
  const action = new NativeFunction(base.add(getterRvas.backend_kbm_action), 'pointer', ['int']);
  const shown = new NativeFunction(base.add(getterRvas.overlay_shown), 'int', []);
  return {shown: shown(), bindings: Array.from({length:22}, (_,index) =>
    ({index, action:action(index).readUtf8String(), key:key(index).readUtf8String()}))};
};
'''
    session = frida.attach(args.pid)
    try:
        script = session.create_script(source)
        script.load()
        result = script.exports_sync.read()
    finally:
        session.detach()
    report = dict(build=build, identity=identity, **result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
