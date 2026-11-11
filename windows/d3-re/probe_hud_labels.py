"""Read HUD key text, integer point sizes and native laid-out text extents.

Uses one serial game-thread probe. No label writes, window activation or cursor
operations. The native text measurement reads the same parsed label and font
arguments as the renderer, rather than treating a setter return as proof.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import frida
import psutil

import probe_guest_call as bridge
import probe_ui_tree
from ui_text import JS as TEXT_JS
from version import EXE, assert_installed

MEASURE_JS = r"""
function measureLabels(cpu, req) {
  const scratch = cpu.add(248).readU64().toNumber() - 0x4000;
  return {ok:true, labels:req.labels.map(label => {
    const obj = label.obj;
    const r = callGuest(cpu, 0x83AC9C0, [obj,scratch,0], null, null);
    return {...label, point_sizes:[0x3AC,0x3B0,0x3B4,0x3B8].map(o=>gp(obj+o).readS32()),
            extent:[gp(scratch).readFloat(),gp(scratch+4).readFloat()], returned:r.returned};
  })};
}
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    process = psutil.Process(args.pid)
    path = Path(process.exe())
    if path.resolve() != EXE.resolve():
        raise SystemExit("process path does not match the validated installation")
    identity = {"pid": args.pid, "path": str(path), "started_at_unix": process.create_time(), **build}
    js = bridge.JS.replace("__CONTEXT__", "null").replace("__FRAME__", "0x804F9C0")
    js = js.replace("__AFTER__", "true").replace("__EVENT__", "0x19")
    js = js.replace("function runCall(cpu, req) {", MEASURE_JS + "\nfunction runCall(cpu, req) {")
    js = js.replace("if (req.mode === 'project') {",
                    "if (req.mode === 'labels') { result = measureLabels(cpu,req); } else if (req.mode === 'project') {")
    js += "\nconst bridgeExports = rpc.exports;\n" + TEXT_JS
    js += probe_ui_tree.JS[probe_ui_tree.JS.index("function rd64"):]
    js += r"""
const dumpUI = rpc.exports.dump;
rpc.exports = bridgeExports;
rpc.exports.labels = () => dumpUI(null,true).items.filter(o=>
  o.rect2[1] >= 650 && o.rect2[1] < 700 && o.text &&
  /^(左键|右键|L|R|[1-4Q]|\{icon:[^}]+\})$/.test(o.text));
"""
    session = frida.attach(args.pid)
    try:
        script = session.create_script(js)
        script.load()
        labels = script.exports_sync.labels()
        if not labels:
            raise SystemExit("world HUD key labels are not visible")
        script.exports_sync.arm({"mode": "labels", "labels": labels})
        deadline = time.monotonic() + 10
        data = {}
        while time.monotonic() < deadline:
            data = script.exports_sync.result()
            if data.get("result"):
                break
            time.sleep(.1)
    finally:
        session.detach()
    data["identity"] = identity
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    result = data.get("result") or {}
    if not result.get("ok"):
        raise SystemExit(result.get("error", "game-thread measurement did not complete"))
    for label in result["labels"]:
        print(label["text"], "points=", label["point_sizes"], "extent=", label["extent"])


if __name__ == "__main__":
    main()
