"""Inject one SDL keyboard down/up pair, without changing OS focus or input."""
from __future__ import annotations

import argparse
import json
import frida
from version import assert_installed, js_consts

KEYS = {"esc": (41, 27), "backspace": (42, 8), "i": (12, 105), "alt": (226, 0x400000E2),
        "space": (44, 32), "enter": (40, 13), "z": (29, 122), "c": (6, 99),
        "v": (25, 118), "q": (20, 113), "e": (8, 101), "tab": (43, 9),
        "f3": (61, 0x4000003D), "right": (79, 0x4000004F),
        "left": (80, 0x40000050), "down": (81, 0x40000051),
        "up": (82, 0x40000052)}
JS = js_consts() + r"""
rpc.exports={key(scan,keycode,phase){
  const win=base.add(RVA.sdl_window).readPointer();
  const id=new NativeFunction(base.add(RVA.sdl_get_window_id),'uint',['pointer'])(win);
  const push=new NativeFunction(base.add(RVA.sdl_push_event),'bool',['pointer']);
  const result=[];
  const phases = phase === 'down' ? [true] : phase === 'up' ? [false] : [true,false];
  for(const down of phases){
    const e=Memory.alloc(128);e.writeByteArray(new Uint8Array(128));
    e.writeU32(down?0x300:0x301);e.add(16).writeU32(id);
    e.add(24).writeU32(scan);e.add(28).writeU32(keycode);e.add(36).writeU8(down?1:0);
    result.push(push(e));
  }
  return {windowId:id,scan,keycode,down:result[0],up:result[1]};
}};
"""


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid",type=int,required=True)
    ap.add_argument("--key",choices=KEYS,required=True)
    ap.add_argument("--phase",choices=("both","down","up"),default="both")
    args=ap.parse_args()
    build=assert_installed()
    session=frida.attach(args.pid)
    try:
        script=session.create_script(JS);script.load()
        data=script.exports_sync.key(*KEYS[args.key],args.phase)
    finally:
        session.detach()
    print(json.dumps({"build":build,**data},indent=2))


if __name__=="__main__":
    main()
