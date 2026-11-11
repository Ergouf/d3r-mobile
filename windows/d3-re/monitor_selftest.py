#!/usr/bin/env python3
"""Self-test of the MemoryAccessMonitor method with a native reader process.

A hidden Python helper allocates the watched page and runs a native reader
(`mov eax,[rcx]; inc dword [rdx]; ret`) on demand; Frida only monitors. The
monitor re-arms asynchronously (on access: disable, then re-enable on the next
tick), so a faulting instruction can complete.

Case 1, one read per arm: arm, one read, wait for the helper's counter, repeat.
  expected: completions == reads, one callback per read, no same-PC storm.
Case 2, one arm then a burst: arm once, then N reads.
  expected: all reads complete; callbacks may be fewer (missed samples recorded).

Usage:
  python windows/d3-re/monitor_selftest.py [--reads 5] [--burst 100] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import frida

HELPER = r'''
import ctypes, json, sys
k = ctypes.windll.kernel32
k.VirtualAlloc.restype = ctypes.c_void_p
watch = k.VirtualAlloc(None, 4096, 0x3000, 4)
done = k.VirtualAlloc(None, 4096, 0x3000, 4)
thunk = k.VirtualAlloc(None, 4096, 0x3000, 0x40)
if not watch or not done or not thunk:
    raise SystemExit('VirtualAlloc failed')
ctypes.c_uint32.from_address(watch).value = 0x1234
ctypes.memmove(thunk, b'\x8b\x01\xff\x02\xc3', 5)   # mov eax,[rcx]; inc dword [rdx]; ret
reader = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)(thunk)
print(json.dumps({'watch': hex(watch), 'done': hex(done), 'read_pc': hex(thunk)}), flush=True)
for line in sys.stdin:
    line = line.strip()
    if line == 'go':
        reader(watch, done)
        print(json.dumps({'done': ctypes.c_uint32.from_address(done).value}), flush=True)
    elif line.startswith('burst'):
        n = int(line.split()[1])
        for _ in range(n):
            reader(watch, done)
        print(json.dumps({'done': ctypes.c_uint32.from_address(done).value}), flush=True)
    elif line == 'exit':
        break
'''

JS = r"""
const watched = ptr(WATCH);
const state = { callbacks: 0, pcs: {}, armed: false, errors: [] };
function arm() {
  try {
    MemoryAccessMonitor.enable([{ base: watched, size: 4096 }], {
      onAccess(d) {
        state.callbacks++;
        const pc = d.from.toString();
        state.pcs[pc] = (state.pcs[pc] || 0) + 1;
        try { MemoryAccessMonitor.disable(); } catch (e) {}
        setTimeout(arm, 1);          /* asynchronous: the instruction completes */
      }
    });
    state.armed = true;
  } catch (e) { state.errors.push('arm: ' + e.message); }
}
rpc.exports = {
  arm: () => arm(),
  reset: () => { state.callbacks = 0; state.pcs = {}; return state; },
  data: () => state,
  disarm: () => { try { MemoryAccessMonitor.disable(); } catch (e) {} state.armed = false; return state; }
};
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reads", type=int, default=5)
    ap.add_argument("--burst", type=int, default=100)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    proc = subprocess.Popen([sys.executable, "-u", "-c", HELPER], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    session = None
    result: dict = {}
    try:
        addresses = json.loads(proc.stdout.readline())
        result["addresses"] = addresses
        session = frida.attach(proc.pid)
        script = session.create_script(JS.replace("WATCH", json.dumps(addresses["watch"])))
        script.load()

        # case 1: one read per arm
        case1 = {"reads": args.reads, "callbacks": 0, "completions": 0, "per_read": []}
        for _ in range(args.reads):
            script.exports_sync.reset()
            script.exports_sync.arm()
            proc.stdin.write("go\n")
            proc.stdin.flush()
            done = json.loads(proc.stdout.readline())["done"]
            data = script.exports_sync.data()
            case1["callbacks"] += data["callbacks"]
            case1["completions"] = done
            case1["per_read"].append({"callbacks": data["callbacks"], "done": done, "pcs": data["pcs"]})
            time.sleep(0.01)
        script.exports_sync.disarm()
        result["case1"] = case1

        # case 2: one arm, then a burst
        done_before = result["case1"]["completions"]
        script.exports_sync.reset()
        script.exports_sync.arm()
        proc.stdin.write("burst %d\n" % args.burst)
        proc.stdin.flush()
        done = json.loads(proc.stdout.readline())["done"]
        data = script.exports_sync.data()
        result["case2"] = {"burst": args.burst, "callbacks": data["callbacks"], "completions": done,
                           "delta": done - done_before, "pcs": data["pcs"]}
        script.exports_sync.disarm()
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
        if proc.poll() is None:
            try:
                proc.stdin.write("exit\n")
                proc.stdin.flush()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    c1 = result.get("case1", {})
    c2 = result.get("case2", {})
    result["verdict"] = {
        "case1_one_callback_per_read": c1.get("callbacks") == args.reads,
        "case1_all_reads_completed": c1.get("completions") == args.reads,
        "case2_all_reads_completed": c2.get("delta") == args.burst,
        "case2_missed_samples": max(0, args.burst - int(c2.get("callbacks") or 0)),
    }
    text = json.dumps(result, indent=2)
    print(text[:3000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
