"""Hook native_world_click and log the arguments of real mouse clicks."""
from __future__ import annotations

import argparse
import json
import time

import frida

from version import assert_installed, js_consts

JS = js_consts() + r"""
const out={calls:[],errors:[]};
const host=base.add(RVA.native_world_click);
Interceptor.attach(host,{onEnter(args){
  try{
    let fx=null,fy=null;
    try{fx=this.context.xmm0.readFloat();}catch(e){}
    try{fy=this.context.xmm1.readFloat();}catch(e){}
    out.calls.push({t:Date.now(),x:fx,y:fy,
      w:args[2].toInt32(),h:args[3].toInt32(),fallback:args[4].toString()});
  }catch(e){out.errors.push(e.message);}
}});
rpc.exports={stop(){return out;}};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=6)
    args = ap.parse_args()
    assert_installed()
    s = frida.get_local_device().attach(args.pid)
    try:
        sc = s.create_script(JS)
        sc.load()
        print("armed; click the game window now")
        time.sleep(args.seconds)
        data = sc.exports_sync.stop()
    finally:
        s.detach()
    print(json.dumps(data, indent=1))


if __name__ == "__main__":
    main()
