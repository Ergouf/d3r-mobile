"""Call the game's inventory selection setter for each valid slot and read its title."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_guest_call as bridge
from version import assert_installed


EXTENSION = r"""
rpc.exports.inventoryState = function() {
  function q(a){return gm.add(a).readU64().toNumber();}
  const controller=q(q(0x9157f58)), title=0x159445a00, prompt=0x15ed81c00;
  function label(obj){
    if(q(obj)!=0x90ae520 && q(obj)!=0x90abb48) return null;
    const p=q(obj+0x398), cap=gm.add(obj+0x3a0).readU32();
    return p && cap>0 && cap<4096 ? gm.add(p).readUtf8String() : null;
  }
  return {controller, selected:gm.add(controller+0x150).readS32(),
    title:label(title), prompt:label(prompt),
    highlighted:q(0x15d47f700+0x538)};
};
"""


def build_js() -> str:
    return (bridge.JS.replace("__CONTEXT__", "null")
            .replace("__FRAME__", "0x80fc310")
            .replace("__AFTER__", "true")
            .replace("__EVENT__", "null") + EXTENSION)


def wait_call(api, controller: int, index: int) -> dict:
    api.arm({"mode": "call", "target": 0x81fcfd0, "args": [controller, index],
             "x8": None, "x8Rel": 0, "s0": None, "dumpLen": 0})
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        state = api.result()
        if state.get("result"):
            if not state["result"].get("ok") or not state["result"].get("returned"):
                raise RuntimeError(f"slot {index}: {state['result']}")
            return state["result"]
        time.sleep(.05)
    raise TimeoutError(f"slot {index} setter timed out")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, default=6032)
    ap.add_argument("--max-index", type=int, default=13)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    results: list[dict] = []
    try:
        script = session.create_script(build_js())
        script.load()
        api = script.exports_sync
        original = api.inventory_state()
        try:
            for index in range(args.max_index + 1):
                call = wait_call(api, original["controller"], index)
                time.sleep(.12)
                state = api.inventory_state()
                row = {"index": index, "call": call, **state}
                results.append(row)
                print(json.dumps({"index": index, "selected": state["selected"],
                                  "title": state["title"], "prompt": state["prompt"]},
                                 ensure_ascii=True), flush=True)
        finally:
            if api.inventory_state()["selected"] != original["selected"]:
                wait_call(api, original["controller"], original["selected"])
    finally:
        session.detach()
    output = {"original": original, "rows": results}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
