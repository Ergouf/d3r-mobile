#!/usr/bin/env python3
"""Mouse A->B->A data-flow check: is a published HID mouse position copied?

For each stage it writes two legal coordinates (buttons=0) into the runtime's
HID mouse state under input_lock, waits until the sampler really advanced
(>=30 samples), verifies the newest LIFO entry carries the coordinates, and
then scans mapped guest memory for the joint (x,y) signature. Every hit keeps
its host address, guest address, mem_query state/perm and raw bytes; the
KShmem host buffer and the guest mapping of the shared memory are excluded.

A->B->A: a candidate is only evidence if the same address follows the values.
No hit is reported as "no copy found in this search", never as "no consumer".

Read-only towards the game: it writes the mouse state and restores it.

Usage:
  python windows/d3-re/mouse_flow.py --pid <pid> --out out/windows/kbm/mouse-flow.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import frida

import version

JS = version.js_consts() + r"""
const hle = base.add(RVA.g_hle_ptr).readPointer();
const kshmem = new NativeFunction(base.add(RVA.kshmem_ptr), 'pointer', ['pointer']);
const pm_lock = new NativeFunction(base.add(0x5FAD0), 'void', ['pointer']);
const pm_unlock = new NativeFunction(base.add(0x5FAE0), 'void', ['pointer']);
const mem_query = new NativeFunction(base.add(RVA.mem_query), 'void', ['uint64', 'pointer']);
const block = Memory.alloc(0x40);

function shmInfo() {
  const obj = hle.add(0x2C8DD8).readPointer();
  const host = obj.add(0x38).readU64().toNumber();
  const pool = obj.add(0x40).readU64().toNumber();
  const gaddr = obj.add(0x48).readU64().toNumber();
  const gsize = obj.add(0x50).readU64().toNumber();
  const actual = kshmem(obj).toString();
  return { obj: obj.toString(), host, pool, gaddr, gsize, actual,
           gp_gaddr: gm.add(ptr(gaddr)).toString() };
}
function mouseState() {
  const m = hle.add(0x2C8DA4);
  return { x: m.readS32(), y: m.add(4).readS32(), buttons: m.add(0x18).readU32(), seen: m.add(0x1C).readS32() };
}
function setMouse(x, y) {
  const lock = hle.add(0x2C8DC8);
  const m = hle.add(0x2C8DA4);
  pm_lock(lock);
  m.writeS32(x);
  m.add(4).writeS32(y);
  m.add(8).writeS32(0);
  m.add(0xC).writeS32(0);
  m.add(0x10).writeS32(0);
  m.add(0x14).writeS32(0);
  m.add(0x18).writeU32(0);
  m.add(0x1C).writeS32(1);
  pm_unlock(lock);
  return mouseState();
}
function samp() { return hle.add(0x2C8E48).readU64().toString(); }
function latest() {
  const info = shmInfo();
  const host = ptr(info.actual);
  const lifo = host.add(0x3400);
  const tail = lifo.add(0x10).readU64().toNumber();
  const e = lifo.add(0x20 + tail * 0x30);
  return { tail, stamp: e.readU64().toString(), sampling: e.add(8).readU64().toString(),
           x: e.add(0x10).readS32(), y: e.add(0x14).readS32(), dx: e.add(0x18).readS32(),
           dy: e.add(0x1C).readS32(), wx: e.add(0x20).readS32(), wy: e.add(0x24).readS32(),
           buttons: e.add(0x28).readU32(), attributes: e.add(0x2C).readU32(), host: host.toString() };
}
function classifyGuest(guest) {
  mem_query(uint64(guest), block);
  return { addr: block.readU64().toString(), size: block.add(8).readU64().toString(),
           state: block.add(16).readU32(), perm: block.add(20).readU32(), attr: block.add(24).readU32(),
           pool: block.add(0x28).readU64().toString() };
}
function scan(pattern, maxSeconds) {
  const started = Date.now();
  const gmem = parseInt(gm.toString(), 16);
  const end = gmem + 0x2000000000;   /* 128 GiB guest reservation */
  const info = shmInfo();
  const shmGuestStart = info.gaddr, shmGuestEnd = info.gaddr + info.gsize;
  const shmHostStart = info.host, shmHostEnd = info.host + info.gsize;
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
        /* the HID shared memory and its service buffer are not copies made by the guest */
        if ((guest >= shmGuestStart && guest < shmGuestEnd) || (host >= shmHostStart && host < shmHostEnd)) {
          aliasHits++;
          continue;
        }
        const rec = { host: host.toString(), guest: guest.toString(), raw: '' };
        try {
          rec.raw = Array.from(new Uint8Array(ptr(host).readByteArray(32)), b => b.toString(16).padStart(2, '0')).join('');
          rec.block = classifyGuest(guest);
        } catch (e) { rec.error = e.message; }
        hits.push(rec);
      }
    } catch (e) { errors++; }
  }
  return { hits, scanned, ranges, skipped, skipped_bytes: skippedBytes, errors, alias_hits: aliasHits,
           elapsed_ms: Date.now() - started, truncated: Date.now() - started > maxSeconds * 1000 };
}
rpc.exports = {
  info: () => ({ exe: exe.path, code: Process.getModuleByName('01001B300B9BE000_code.dll').path,
                 gmem: gm.toString(), hle: hle.toString(), shm: shmInfo() }),
  state: mouseState, set: setMouse, samp, latest, scan, classify: classifyGuest
};
"""


def wait_samples(api, minimum: int, timeout: float) -> dict:
    """Wait until the published LIFO sampling number advanced by `minimum`."""
    start = int(api.latest()["sampling"])
    deadline = time.time() + timeout
    last = start
    while time.time() < deadline:
        time.sleep(0.05)
        last = int(api.latest()["sampling"])
        if last - start >= minimum:
            return {"start": start, "end": last, "advance": last - start, "ok": True}
    return {"start": start, "end": last, "advance": last - start, "ok": False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--min-samples", type=int, default=30)
    ap.add_argument("--scan-seconds", type=float, default=90.0)
    args = ap.parse_args()

    version.assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(JS)
    script.load()
    api = script.exports_sync
    result = {"pid": args.pid, "info": api.info(), "stages": []}
    original = api.state()
    result["original"] = original
    plan = [("A1", 111, 222), ("B", 333, 444), ("A2", 111, 222)]
    try:
        for name, x, y in plan:
            written = api.set(x, y)
            wait = wait_samples(api, args.min_samples, 8.0)
            latest = api.latest()
            published_ok = latest["x"] == x and latest["y"] == y
            stage = {"name": name, "written": written, "wait": wait, "latest": latest,
                     "published_ok": published_ok, "valid": wait["ok"] and published_ok}
            if stage["valid"]:
                pattern = " ".join("%02x" % b for b in (x.to_bytes(4, "little", signed=True) +
                                                        y.to_bytes(4, "little", signed=True)))
                stage["pattern"] = pattern
                stage["scan"] = api.scan(pattern, args.scan_seconds)
            result["stages"].append(stage)
            if not stage["valid"]:
                break
        # candidate follow-up: same guest address in every valid stage
        valid = [s for s in result["stages"] if s["valid"]]
        if len(valid) == 3:
            sets = [{h["guest"] for h in s["scan"]["hits"]} for s in valid]
            common = set.intersection(*sets)
            result["candidates_all_stages"] = sorted(common, key=lambda v: int(v))
    finally:
        api.set(original["x"], original["y"] if original["y"] is not None else 0)
        session.detach()
    text = json.dumps(result, indent=2)
    print(text[:6000])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
