"""Print the SDL window size and the game's UI viewport rect for one PID."""
from __future__ import annotations

import argparse
import json

import frida
from version import assert_installed, js_consts

JS = js_consts() + r"""
rpc.exports={info(){
  const win=base.add(RVA.sdl_window).readPointer();
  const size=Memory.alloc(8);
  new NativeFunction(base.add(RVA.sdl_get_window_size),'bool',['pointer','pointer','pointer'])(win,size,size.add(4));
  const rect=Memory.alloc(16);
  const ok=new NativeFunction(resolveGuest(0x8042940),'bool',['pointer'])(rect);
  const gp=resolveGuest(0x8042940);
  return {window:[size.readS32(),size.add(4).readS32()],rectOk:ok,
    rect:[rect.readS32(),rect.add(4).readS32(),rect.add(8).readS32(),rect.add(12).readS32()],
    viewportHost:gp?gp.toString():null};
}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    args = ap.parse_args()
    build = assert_installed()
    session = frida.attach(args.pid)
    try:
        script = session.create_script(JS)
        script.load()
        data = script.exports_sync.info()
    finally:
        session.detach()
    print(json.dumps({"build": build, **data}, indent=2))


if __name__ == "__main__":
    main()
