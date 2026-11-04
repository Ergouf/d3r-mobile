"""Call one guest function on the game thread with integer arguments.

Uses the same isolated-CPU bridge as the other probes: full CPU copy, private
guest stack, only a complete `pc == 0` return is reported.

Usage:
  python tools/d3-re/probe_guest_ui.py --pid 1234 --context 0x... --pc 0x838a6e0 --args 0x15d...,0
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
function callOne(cpu, req) {
  let args = req.args.map(v => (typeof v === 'string' ? Number(BigInt(v)) : v));
  let event = null;
  if (req.event !== null && req.event !== undefined) {
    /* a synthetic UI event: {type:u32, ...} on a private guest scratch page */
    /* the bridge's own guest stack is mapped; cpu->sp is not always valid here */
    const alloc = new NativeFunction(runtimeModule.base.add(RVA.kmem_alloc), 'uint64',
                                     ['uint64', 'uint', 'uint']);
    event = alloc(0x100, 0x045C3C0B, 3).toNumber();
    if (!event) throw new Error('no guest scratch for the event');
    gp(event).writeU32(req.event);
    gp(event + 4).writeU32(0);
    gp(event + 8).writeU32(0);
    gp(event + 12).writeU32(0);
    args = [args[0], event, args[1] || 0];
  }
  const r = callGuest(cpu, req.pc, args, null, null);
  return {pc: req.pc, args: req.args, event: req.event === undefined ? null : req.event,
          eventPtr: event === null ? null : '0x' + event.toString(16),
          ret: r.ret, returned: r.returned, steps: r.steps, error: r.error || null};
}
"""


def build_js(context: int, frame: int) -> str:
    js = bridge.JS.replace("__CONTEXT__", hex(context)).replace("__FRAME__", hex(frame))
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "0x19")
    js = js.replace("function runCall(cpu, req) {", EXTENSION + "\nfunction runCall(cpu, req) {")
    return js.replace("if (req.mode === 'project') {",
                      "if (req.mode === 'call') { result = callOne(cpu, req); } "
                      "else if (req.mode === 'project') {")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", type=lambda s: int(s, 0), default=0x150030E60,
                    help="TLS context of the game thread; a stale value makes the probe a no-op")
    ap.add_argument("--pc", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--args", default="")
    ap.add_argument("--frame", type=lambda s: int(s, 0), default=0x804f9c0)
    ap.add_argument("--event", type=lambda s: int(s, 0), default=None,
                    help="EXPERIMENTAL and currently unusable: the guest scratch for the synthetic event is not mapped in the UI callback")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    if args.event is not None:
        raise SystemExit("--event is unusable: the synthetic event path faults inside callGuest "
                         "at a fixed bogus address; see KBM-RE-EVIDENCE 18.56")
    values = [v.strip() for v in args.args.split(",") if v.strip()]
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(build_js(args.context, args.frame))
        script.on("message", lambda m, d: print(m, flush=True) if m.get("type") == "error" else None)
        script.load()
        req = {"mode": "call", "pc": args.pc, "args": values, "event": args.event}
        script.exports_sync.arm(req)
        deadline = time.monotonic() + 10
        data = {}
        while time.monotonic() < deadline:
            data = script.exports_sync.result()
            if data.get("result"):
                break
            time.sleep(0.1)
    finally:
        session.detach()
    data["build"] = build
    data["req"] = req
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2), "utf-8")
    if not data.get("result"):
        raise SystemExit("no frame anchor hit (frameCalls=%s) - wrong --frame/--context?"
                         % data.get("frameCalls"))
    print(json.dumps(data["result"], indent=2))


if __name__ == "__main__":
    main()
