#!/usr/bin/env python3
"""Pad A->B->A data-flow check: does the guest copy the pad button mask?

The frontend republishes `g_hle.hid.pad1` every frame, so the marker is
rewritten every millisecond under `input_lock` for the whole stage; the guest
samples at frame rate and therefore sees it. Each stage then scans mapped guest
memory for the 8-byte mask, excluding the HID shared memory and its service
buffer, and only addresses that follow A->B->A count as a copy.

Usage:
  python tools/d3-re/pad_flow.py --pid <pid> --out out/windows/kbm/pad-flow.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida

import version

JS = version.js_consts() + r"""
const hle = base.add(RVA.g_hle_ptr).readPointer();
const kshmem = new NativeFunction(base.add(RVA.kshmem_ptr), 'pointer', ['pointer']);
const pm_lock = new NativeFunction(base.add(0x5FAD0), 'void', ['pointer']);
const pm_unlock = new NativeFunction(base.add(0x5FAE0), 'void', ['pointer']);
const mem_query = new NativeFunction(base.add(RVA.mem_query), 'void', ['uint64', 'pointer']);
const block = Memory.alloc(0x40);
let timer = null, current = '0x0';

function shmInfo() {
  const obj = hle.add(HLE.shm).readPointer();
  const host = obj.add(0x38).readU64().toNumber();
  const gaddr = obj.add(0x48).readU64().toNumber();
  const gsize = obj.add(0x50).readU64().toNumber();
  return { host, gaddr, gsize, actual: kshmem(obj).toString() };
}
function setButtons(v) {
  const lock = hle.add(0x2C8DC8);
  pm_lock(lock);
  hle.add(HLE.pad_buttons).writeU64(uint64(v));
  pm_unlock(lock);
}
function start(markerHz) {
  current = markerHz;
  if (timer !== null) return true;
  /* write the marker at the sampler's entry, before it copies pad1: the frontend overwrites pad1 every frame, so a
     timer cannot win the race, but this hook is exactly before the sample is taken */
  timer = Interceptor.attach(base.add(RVA.hid_update), {
    onEnter() { hle.add(HLE.pad_buttons).writeU64(uint64(current)); }
  });
  return true;
}
function stop() {
  if (timer !== null) { try { timer.detach(); } catch (e) {} timer = null; }
  setButtons('0x0');
  return true;
}
function samp() { return hle.add(0x2C8E48).readU64().toString(); }
function scan(pattern, maxSeconds) {
  const started = Date.now();
  const gmem = parseInt(gm.toString(), 16);
  const end = gmem + 0x2000000000;
  const info = shmInfo();
  const shmStart = info.gaddr, shmEnd = info.gaddr + info.gsize;
  const hits = [];
  let scanned = 0, ranges = 0, skipped = 0, skippedBytes = 0, errors = 0, aliasHits = 0;
  for (const r of Process.enumerateRanges('rw-')) {
    const start = parseInt(r.base.toString(), 16);
    if (start < gmem || start + r.size > end) { skipped++; skippedBytes += r.size; continue; }
    if (Date.now() - started > maxSeconds * 1000) break;
    try {
      const found = Memory.scanSync(r.base, r.size, pattern);
      scanned += r.size;
      ranges++;
      for (const f of found) {
        const host = parseInt(f.address.toString(), 16);
        const guest = host - gmem;
        if (guest >= shmStart && guest < shmEnd) { aliasHits++; continue; }
        const rec = { guest: guest.toString(), raw: '' };
        try {
          rec.raw = Array.from(new Uint8Array(ptr(host).readByteArray(32)), b => b.toString(16).padStart(2, '0')).join('');
          mem_query(uint64(guest), block);
          rec.state = block.add(16).readU32();
          rec.perm = block.add(20).readU32();
          rec.addr = block.readU64().toString();
          rec.size = block.add(8).readU64().toString();
        } catch (e) { rec.error = e.message; }
        hits.push(rec);
      }
    } catch (e) { errors++; }
  }
  return { hits, scanned, ranges, skipped, skipped_bytes: skippedBytes, errors, alias_hits: aliasHits,
           elapsed_ms: Date.now() - started };
}
rpc.exports = { info: () => ({ gmem: gm.toString(), shm: shmInfo() }), start, stop, samp, scan };
"""


def wait_advance(api, minimum: int, timeout: float) -> dict:
    start = int(api.samp())
    deadline = time.time() + timeout
    last = start
    while time.time() < deadline:
        time.sleep(0.05)
        last = int(api.samp())
        if last - start >= minimum:
            return {"start": start, "end": last, "advance": last - start, "ok": True}
    return {"start": start, "end": last, "advance": last - start, "ok": False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--min-samples", type=int, default=30)
    ap.add_argument("--scan-seconds", type=float, default=30.0)
    args = ap.parse_args()
    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync
    info = api.info()
    result = {"pid": args.pid, "info": info, "stages": []}
    plan = [("A1", 0xABC00001), ("B", 0x12340002), ("A2", 0xABC00001)]
    try:
        api.start("0x0")
        for name, marker in plan:
            api.start(hex(marker))
            wait = wait_advance(api, args.min_samples, 8.0)
            pattern = " ".join("%02x" % b for b in marker.to_bytes(8, "little"))
            stage = {"name": name, "marker": hex(marker), "wait": wait}
            if wait["ok"]:
                stage["scan"] = api.scan(pattern, args.scan_seconds)
            result["stages"].append(stage)
            if not wait["ok"]:
                break
        valid = [s for s in result["stages"] if s.get("scan")]
        if len(valid) == 3:
            sets = [{h["guest"] for h in s["scan"]["hits"]} for s in valid]
            result["candidates_all_stages"] = sorted(set.intersection(*sets), key=lambda v: int(v))
    finally:
        try:
            api.stop()
        finally:
            session.detach()
    text = json.dumps(result, indent=2)
    print(text[:4000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
