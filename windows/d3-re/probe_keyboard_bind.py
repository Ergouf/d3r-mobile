"""Set or reset native KBM bindings through the same backend used by F2."""
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
    parser.add_argument('--set', action='append', default=[], metavar='INDEX=KEY')
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.reset and args.set:
        parser.error('use either --reset or --set')
    changes = []
    for item in args.set:
        before, _, key = item.partition('=')
        try:
            index = int(before, 0)
        except ValueError:
            parser.error(f'invalid index in {item!r}')
        if not key or index < 0:
            parser.error(f'invalid binding {item!r}')
        changes.append((index, key))

    build = version.assert_installed()
    identity = session_driver._process_identity(args.pid)
    symbols = version._symbol_table(version.EXE)
    wanted = ['backend_kbm_key', 'backend_kbm_action', 'backend_kbm_bind',
              'backend_kbm_reset', 'SDL_GetScancodeFromName']
    missing = [name for name in wanted if name not in symbols]
    if missing:
        raise SystemExit(f'missing symbols: {missing}')
    rvas = {name: symbols[name] for name in wanted}
    source = version.js_consts() + chr(10) + 'const rvas=' + json.dumps(rvas) + r''';
rpc.exports.run = (changes, resetFlag) => {
  const key = new NativeFunction(base.add(rvas.backend_kbm_key), 'pointer', ['int']);
  const action = new NativeFunction(base.add(rvas.backend_kbm_action), 'pointer', ['int']);
  const bind = new NativeFunction(base.add(rvas.backend_kbm_bind), 'int', ['int', 'int']);
  const reset = new NativeFunction(base.add(rvas.backend_kbm_reset), 'int', []);
  const scan = new NativeFunction(base.add(rvas.SDL_GetScancodeFromName), 'int', ['pointer']);
  const applied = changes.map(([index, name]) => {
    const scancode = scan(Memory.allocUtf8String(name));
    return {index, name, scancode, accepted: bind(index, scancode)};
  });
  if (resetFlag) applied.push({reset: reset()});
  return {applied, bindings: Array.from({length:22}, (_,index) =>
    ({index, action:action(index).readUtf8String(), key:key(index).readUtf8String()}))};
};
'''
    session = frida.attach(args.pid)
    try:
        script = session.create_script(source)
        script.load()
        result = script.exports_sync.run(changes, args.reset)
    finally:
        session.detach()
    report = dict(build=build, identity=identity, **result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
