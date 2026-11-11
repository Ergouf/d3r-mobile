"""Resolve Actor SNO names using the game's own script-backed name getter.

The Lua ActorGetNameFromSNO wrapper at 0x88E3670 calls 0x8948290(sno),
returning a String through x8. Read its buffer and destroy the temporary
String as that wrapper does. No movement, input or interaction is submitted.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import probe_guest_call as bridge
from version import assert_installed

EXTENSION = r"""
function actorNames(cpu, req) {
  const address=cpu.add(248).readU64().toNumber()-0x20000, names=[];
  for(const sno of req.snos){
    gp(address).writeByteArray(new Uint8Array(32));
    const lookup=callGuest(cpu,0x8948290,[sno],address,null);
    if(!lookup.returned){names.push({sno,lookup});break;}
    let text=null, error=null, cleanup=null, buffer=null;
    try{
      buffer=gp(address+8).readU64().toNumber();
      if(buffer){
        const bytes=new Uint8Array(gp(buffer).readByteArray(512)), length=bytes.indexOf(0);
        if(length<0)throw new Error('Actor name has no terminator within 512 bytes');
        text=length?gp(buffer).readUtf8String(length):'';
      }
    }catch(e){error=String(e);}
    finally{cleanup=callGuest(cpu,0x8a4df10,[address],null,null);}
    names.push({sno,text,buffer,error,lookup,cleanup});
    if(!cleanup.returned)break;
  }
  return {names};
}
"""


def build_js(context: int) -> str:
    js = bridge.JS.replace("__CONTEXT__", hex(context)).replace("__FRAME__", "0x804f9c0")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "0x19")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
                      "if (req.mode === 'actor_names') { result = actorNames(cpu, req); } "
                      "else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=0x150030E60)
    ap.add_argument("--sno", nargs="+", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if len(args.sno) > 32 or any(s < 0 or s > 0x7fffffff for s in args.sno):
        ap.error("use 1..32 nonnegative 32-bit Actor SNOs")
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    errors = []
    try:
        script = session.create_script(build_js(args.context))
        script.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        script.load()
        script.exports_sync.arm({"mode": "actor_names", "snos": args.sno})
        deadline = time.monotonic() + 10
        data = {}
        while time.monotonic() < deadline:
            data = script.exports_sync.result()
            if data.get("result") or errors:
                break
            time.sleep(0.1)
    finally:
        session.detach()
    data.update(pid=args.pid, build=build, observer_errors=errors)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = data.get("result")
    if not isinstance(result, dict) or not result or errors:
        raise SystemExit("name probe did not complete; see output")
    if (result.get("ok") is False or result.get("error") or result.get("restore_error") or
            result.get("cpu_isolated") is not True):
        raise SystemExit("guest bridge failed or did not preserve its isolated CPU; see output")
    names = result.get("names")
    if (not isinstance(names, list) or len(names) != len(args.sno) or
            any(not isinstance(name, dict) for name in names) or
            [name.get("sno") for name in names] != args.sno):
        raise SystemExit("incomplete or mismatched Actor SNO results; see output")
    for name in names:
        lookup, cleanup = name.get("lookup"), name.get("cleanup")
        if (name.get("error") or not isinstance(name.get("text"), str) or not name["text"] or
                not isinstance(lookup, dict) or lookup.get("returned") is not True or lookup.get("error") or
                not isinstance(cleanup, dict) or cleanup.get("returned") is not True or cleanup.get("error")):
            raise SystemExit("name lookup or cleanup failed; see output")
    for name in names:
        print(name["sno"], name["text"], "lookup", name["lookup"]["returned"],
              "cleanup", name["cleanup"]["returned"])


if __name__ == "__main__":
    main()
