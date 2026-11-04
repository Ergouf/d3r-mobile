"""Observe-only event/return recorder, with an optional single-action diagnostic.

Records, without touching game state in observe mode:
  * every dispatch into 0x82B80C0: guest entry (args[1]), outer bank index (w1),
    event type / event.player / bit, frame counter
  * every call into the registered callbacks 0x8331490 (UI) and 0x804F9C0 (game),
    linked to the dispatch by event id; a return is complete only when CPU.pc
    equals the guest LR saved at callback entry
  * per-frame ticks at 0x800F9F0 with LR == 0x82B94E0 (the input-loop frame mark)

Diagnostic modes press Plus once through the runtime sampler ("pad") or through
the pre-consumer logical write ("inject"), one action per phase, then keep
recording so the release and the following frames are captured.

Usage:
  python tools/d3-re/probe_event_returns.py --pid <pid> [--mode observe|pad|inject|both] [--out ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import frida

import version

JS = version.js_consts() + r"""
const TARGET_EVENT = 0x82B80C0;
const TICK = 0x800F9F0;
const PRE_LR = 0x82B94E0;
const R = 0x9839FF8;
const CB = { ui: 0x8331490, game: 0x804F9C0 };
const ENABLE_PAD = __ENABLE_PAD__;
const ENABLE_INJECT = __ENABLE_INJECT__;
const EXPECTED_MODULES = __EXPECTED_MODULES__;
const out = { hosts: {}, dispatch: [], cb: [], leaves: [], tick: [], errors: [],
              clock_returns: [], writes: { pad: 0, logical: 0 },
              dropped: { leaves: 0, clock_returns: 0 },
              enabled_inputs: { pad: ENABLE_PAD, logical: ENABLE_INJECT },
              counts: { dispatch: 0, ui: 0, game: 0, tick: 0 } };
let injBit = 0, padMask = '0x0', frame = 0;
const currentByCpu = new Map();
function norm(path) { return path.replace(/\\/g, '/').toLowerCase(); }
const code = Process.enumerateModules().find(m => m.name.toLowerCase() === '01001b300b9be000_code.dll');
if (!code || norm(exe.path) !== EXPECTED_MODULES[0] || norm(code.path) !== EXPECTED_MODULES[1])
  throw new Error('target PID module paths do not match the version profile');
out.modules = { exe: exe.path, code: code.path };
for (const pc of [TICK, TARGET_EVENT, CB.ui, CB.game])
  if (!resolveGuest(pc)) throw new Error('missing guest target: 0x' + pc.toString(16));

function ent(args) { try { return parseInt(args[1].toString(), 16); } catch (e) { return -1; } }
function u32(g) { return gm.add(ptr(g)).readU32(); }
function hook(guest, cb) {
  const h = resolveGuest(guest);
  out.hosts[guest.toString(16)] = h ? h.toString() : null;
  if (h) Interceptor.attach(h, cb);
  return !!h;
}
const hle = ENABLE_PAD ? base.add(RVA.g_hle_ptr).readPointer() : null;
if (ENABLE_PAD) Interceptor.attach(base.add(RVA.hid_update), {
  onEnter() { hle.add(HLE.pad_buttons).writeU64(uint64(padMask)); out.writes.pad++; }
});

hook(TICK, {
  onEnter(args) {
    this.clockCpu = null;
    if (ent(args) !== TICK) return;
    let lr = 0;
    try { lr = parseInt(args[0].add(240).readPointer().toString(), 16); } catch (e) {}
    if (lr !== PRE_LR) return;
    const cpu = args[0];
    const player = parseInt(cpu.add(19 * 8).readPointer().toString(), 16);
    const r = parseInt(cpu.add(24 * 8).readPointer().toString(), 16);
    if (player !== 0 || r !== R) return;
    this.clockCpu = cpu;
    out.counts.tick++;
    frame++;
    if (out.tick.length < 20000) out.tick.push(Date.now());
    if (ENABLE_INJECT && injBit) {
      try { const p = R + 0x370; gm.add(ptr(p)).writeU32((u32(p) | injBit) >>> 0); out.writes.logical++; }
      catch (e) { if (out.errors.length < 10) out.errors.push('i:' + e.message); }
    }
  },
  onLeave() {
    if (!this.clockCpu) return;
    try {
      const pc = parseInt(this.clockCpu.add(0x100).readPointer().toString(), 16);
      if (out.clock_returns.length < 3000) out.clock_returns.push({
        t: Date.now(), pc, expected_return: PRE_LR, complete: pc === PRE_LR,
        x0: parseInt(this.clockCpu.readPointer().toString(), 16)
      }); else out.dropped.clock_returns++;
    } catch (e) { if (out.errors.length < 10) out.errors.push('clock:' + e.message); }
  }
});

hook(TARGET_EVENT, {
  onEnter(args) {
    if (ent(args) !== TARGET_EVENT) return;
    out.counts.dispatch++;
    const cpu = args[0];
    let rec = null;
    try {
      const ev = parseInt(cpu.add(0).readPointer().toString(), 16);
      const bank = parseInt(cpu.add(8).readPointer().toString(), 16);
      rec = { id: out.dispatch.length + 1, t: Date.now(), frame, ev,
              cpu: cpu.toString(), tid: Process.getCurrentThreadId(),
              bank, type: u32(ev), player: u32(ev + 0x28), bit: u32(ev + 0x2C), cbs: [] };
      out.dispatch.push(rec);
    } catch (e) { if (out.errors.length < 10) out.errors.push('d:' + e.message); }
    currentByCpu.set(cpu.toString(), rec);
  }
});

function cbHook(name, guest) {
  const h = resolveGuest(guest);
  out.hosts[name] = h ? h.toString() : null;
  if (!h) return;
  Interceptor.attach(h, {
    onEnter(args) {
      this.rec = null;
      if (ent(args) !== guest) return;
      out.counts[name]++;
      const cpu = args[0];
      const cur = currentByCpu.get(cpu.toString());
      const rec = { name, id: cur ? cur.id : null, t: Date.now(), frame, leaves: [] };
      try {
        rec.ev = parseInt(cpu.readPointer().toString(), 16);
        rec.expected_return = parseInt(cpu.add(240).readPointer().toString(), 16);
        rec.tid = Process.getCurrentThreadId();
        rec.correlation_valid = !!cur && cur.type === u32(rec.ev) &&
          cur.player === u32(rec.ev + 0x28) && cur.bit === u32(rec.ev + 0x2C);
        if (!rec.correlation_valid) throw new Error('callback/dispatch correlation mismatch');
      } catch (e) { if (out.errors.length < 10) out.errors.push('cb:' + e.message); }
      out.cb.push(rec);
      if (cur) cur.cbs.push(name);
      this.rec = rec; this.cpu = cpu;
    },
    onLeave(retval) {
      const rec = this.rec;
      if (!rec) return;
      let x0 = null, pc = null;
      try {
        x0 = parseInt(this.cpu.readPointer().toString(), 16);
        pc = parseInt(this.cpu.add(0x100).readPointer().toString(), 16);
      } catch (e) { if (out.errors.length < 10) out.errors.push('leave:' + e.message); }
      const leaf = { x0, pc, expected_return: rec.expected_return,
                     complete: pc === rec.expected_return,
                     correlation_valid: rec.correlation_valid,
                     retval: retval.toString(), t: Date.now() };
      rec.leaves.push(leaf);
      if (out.leaves.length < 6000) out.leaves.push({ name: rec.name, id: rec.id, ...leaf });
      else out.dropped.leaves++;
    }
  });
}
cbHook('ui', CB.ui);
cbHook('game', CB.game);

rpc.exports = {
  setPad(v) {
    if (v && !ENABLE_PAD) throw new Error('pad writes disabled in this mode');
    padMask = '0x' + v.toString(16);
  },
  arm(v) {
    if (v && !ENABLE_INJECT) throw new Error('logical writes disabled in this mode');
    injBit = v;
  },
  data: () => out,
  stop() {
    injBit = 0; padMask = '0x0';
    if (ENABLE_PAD) { hle.add(HLE.pad_buttons).writeU64(uint64('0x0')); out.writes.pad++; }
    out.final_words = { previous: u32(R + 0x338), current: u32(R + 0x370) };
    return out;
  }
};
"""


def summarize(data: dict, t0: int, t1: int) -> dict:
    events = [e for e in data["dispatch"] if t0 <= e["t"] < t1]
    event_ids = {e["id"] for e in events}
    all_leaves = [x for x in data["leaves"] if x["id"] in event_ids]
    leaves = [x for x in all_leaves if x.get("complete") and x.get("correlation_valid")]
    calls = [c for c in data["cb"] if c["id"] in event_ids]
    ticks = [t for t in data["tick"] if t0 <= t < t1]
    button = [e for e in events if e["type"] in (0x1D, 0x1E, 0x21)]
    seq = [(hex(e["type"]), e["bit"], e["bank"], e["cbs"]) for e in button]

    def val(rows, key):
        out = {}
        for r in rows:
            k = str(r.get(key))
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items())[:6])

    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    return {
        "dispatch": len(events),
        "incomplete_leaves": sum(not x.get("complete") for x in all_leaves),
        "button_seq": seq[:12],
        "button_counts": {t: sum(1 for e in button if hex(e["type"]) == t)
                          for t in ("0x1d", "0x1e", "0x21")},
        "ui_calls": sum(1 for c in calls if c["name"] == "ui"),
        "game_calls": sum(1 for c in calls if c["name"] == "game"),
        "ui_leave_x0": val([x for x in leaves if x["name"] == "ui"], "x0"),
        "game_leave_x0": val([x for x in leaves if x["name"] == "game"], "x0"),
        "ui_retval": val([x for x in leaves if x["name"] == "ui"], "retval"),
        "game_retval": val([x for x in leaves if x["name"] == "game"], "retval"),
        "ticks": len(ticks),
        "max_tick_gap_ms": max(gaps) if gaps else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--mode", choices=("observe", "pad", "inject", "both"), default="observe")
    ap.add_argument("--pad-bit", type=lambda s: int(s, 0), default=0x400)
    ap.add_argument("--inj-bit", type=lambda s: int(s, 0), default=0x1000)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    version.assert_installed()
    plan = [("observe0", 0, 0, 1.2)]
    if args.mode in ("pad", "both"):
        plan += [("pad_key", args.pad_bit, 0, 0.15), ("after_pad", 0, 0, 1.3)]
    if args.mode in ("inject", "both"):
        plan += [("inject_key", 0, args.inj_bit, 0.15), ("after_inject", 0, 0, 1.3)]
    plan += [("observe1", 0, 0, 0.8)]
    marks = []
    paths = [str(p).replace("\\", "/").lower() for p in (version.EXE, version.CODE_DLL)]
    js = (JS.replace("__ENABLE_PAD__", str(args.mode in ("pad", "both")).lower())
          .replace("__ENABLE_INJECT__", str(args.mode in ("inject", "both")).lower())
          .replace("__EXPECTED_MODULES__", json.dumps(paths)))
    session = frida.get_local_device().attach(args.pid)
    script = None
    api = None
    data = None
    try:
        script = session.create_script(js)
        script.load()
        api = script.exports_sync
        for name, pad, inj, seconds in plan:
            t0 = int(time.time() * 1000)
            api.set_pad(pad)
            api.arm(inj)
            time.sleep(seconds)
            marks.append((name, t0, int(time.time() * 1000)))
    finally:
        try:
            if api is not None:
                data = api.stop()
        finally:
            try:
                if script is not None:
                    script.unload()
            finally:
                session.detach()

    hosts = data["hosts"]
    print("hosts", hosts)
    print("counts", data["counts"], "errors", data["errors"][:3])
    summary = {}
    for name, t0, t1 in marks:
        summary[name] = summarize(data, t0, t1)
        print(name, json.dumps(summary[name])[:500])
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"pid": args.pid, "mode": args.mode, "modules": data["modules"],
                           "enabled_inputs": data["enabled_inputs"], "writes": data["writes"],
                           "dropped": data["dropped"], "final_words": data["final_words"],
                           "hosts": hosts, "marks": marks,
                           "summary": summary, "counts": data["counts"],
                           "errors": data["errors"], "dispatch": data["dispatch"],
                           "callbacks": data["cb"], "leaves": data["leaves"],
                           "clock_returns": data["clock_returns"], "tick": data["tick"]}, indent=2)
        args.out.write_text(text, encoding="utf-8")
    if (data["errors"] or not data["dispatch"]
            or not data["clock_returns"] or any(data["dropped"].values())
            or any(not x.get("complete") for x in data["leaves"])
            or any(not x["complete"] for x in data["clock_returns"])
            or (args.mode in ("inject", "both") and not data["writes"]["logical"])
            or (args.mode == "observe" and any(data["writes"].values()))):
        raise SystemExit("probe failed or guest-return boundary incomplete; inspect recorded data")


if __name__ == "__main__":
    main()
