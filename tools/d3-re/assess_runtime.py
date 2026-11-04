#!/usr/bin/env python3
"""Bounded runtime observer for native-input RE; never sends UI input.

GuestFn has host ABI (CPU*, guest_entry). ARM64 registers live in CPU.x,
not in Frida's x64 host context. Hooks are temporary and removed on detach.
RVA defaults apply only to the SHA-256 recorded in docs/windows/HANDOFF-20261104-CURRENT.md.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

import frida

JS = r"""
const P = PAYLOAD;
const exe = Process.enumerateModules().find(m => m.name.toLowerCase() === '01001b300b9be000.exe');
if (!exe) throw new Error('Game runtime not loaded');
const gm = exe.base.add(P.g_mem).readPointer();
const disp = exe.base.add(P.g_disp).readPointer();
const lo = exe.base.add(P.g_code_lo).readU64().toNumber();
const hi = exe.base.add(P.g_code_hi).readU64().toNumber();
const mod = Process.getModuleByName('01001B300B9BE000_code.dll');
const desc = new NativeFunction(mod.getExportByName('snx_module'), 'pointer', [])();
const mods = desc.add(8).readPointer();
const modules = [];
for (let i = 0; i < desc.add(4).readU32(); i++) {
  const m = mods.add(i * 88);
  modules.push({name: m.readPointer().readCString(), base: m.add(8).readPointer().toString(),
    size: m.add(16).readU64().toNumber(), text_off: m.add(56).readU32(), text_size: m.add(60).readU32(),
    ro_off: m.add(64).readU32(), ro_size: m.add(68).readU32(),
    data_off: m.add(72).readU32(), data_size: m.add(76).readU32(), bss_size: m.add(80).readU32()});
}
const main = modules.find(m => m.name === 'main');
if (!main || lo <= 0 || hi <= lo) throw new Error('Invalid module or dispatch bounds');
if (gm.add(0x8dcf212).readCString() !== 'UI_HUD_ClickPredicate') throw new Error('Guest baseline string mismatch');
const readptr = a => gm.add(a).readPointer();
const listeners = [], stats = {};
function resolve(g) {
  if (g < lo || g >= hi || (g % 4)) return null;
  const f = disp.add(((g - lo) / 4) * 8).readPointer();
  return f.isNull() ? null : f;
}
function cpuRecord(cpu, entry, ctx) {
  if (!cpu.add(0x350).readPointer().equals(gm)) throw new Error('Host argument is not matching CPU*');
  const x = [];
  for (let i = 0; i < 4; i++) x.push(cpu.add(i * 8).readPointer().toString());
  let vt = null;
  try { vt = readptr(ptr(x[0])).toString(); } catch (_) {}
  return {host_arch: Process.arch, host_has_x0: ctx.x0 !== undefined,
    host_rcx: ctx.rcx ? ctx.rcx.toString() : null, cpu: cpu.toString(), entry: entry.toString(),
    guest_pc: cpu.add(0x100).readPointer().toString(), guest_x: x, guest_x0_vtable: vt,
    guest_lr: cpu.add(30 * 8).readPointer().toString(),
    tls: cpu.add(0x320).readPointer().toString(), tls_ro: cpu.add(0x328).readPointer().toString(),
    guest_thread: cpu.add(0x378).readPointer().toString()};
}
function hook(g) {
  const host = resolve(g);
  const key = '0x' + g.toString(16);
  const st = stats[key] = {host: host ? host.toString() : null, calls: 0, matched_calls: 0,
    object_filter: P.object_filter, errors: 0, entries: {}, threads: {}, samples: []};
  if (!host) return;
  listeners.push(Interceptor.attach(host, {onEnter(args) {
    st.calls++;
    const e = args[1].toString(), t = String(this.threadId);
    st.entries[e] = (st.entries[e] || 0) + 1;
    st.threads[t] = (st.threads[t] || 0) + 1;
    if (P.object_filter !== null && !args[0].readPointer().equals(ptr(P.object_filter))) return;
    st.matched_calls++;
    if (st.samples.length >= P.samples) return;
    try { st.samples.push(cpuRecord(args[0], args[1], this.context)); }
    catch (err) { st.errors++; if (st.errors <= 2) send({event: 'callback_error', target: key, error: err.message}); }
  }}));
}
rpc.exports = {
  info() { return {arch: Process.arch, exe: exe.path, exe_base: exe.base.toString(), code_dll: mod.path,
    gmem: gm.toString(), code_lo: lo, code_hi: hi, modules}; },
  snapshot(names) {
    const start = Date.now();
    const p1 = readptr(0x914f840), p2 = readptr(p1.add(0x10)), p3 = readptr(p2.add(0xb80));
    const map = readptr(p3), mask = gm.add(map).readU32(), before = gm.add(map).add(4).readU32();
    if (mask > 1048575 || before > 1000000) throw new Error('Unreasonable registry size');
    const buckets = readptr(map.add(0x10));
    const wanted = new Map(names.map(n => [n.hash, {name: n.name, found: false}]));
    let visited = 0;
    for (let b = 0; b <= mask; b++) {
      let node = readptr(buckets.add(b * 8)), guard = 0;
      while (!node.isNull()) {
        if (++guard > 1000 || ++visited > before + 1024) throw new Error('Registry changed or cyclic');
        const hash = gm.add(node).add(8).readU64().toString();
        if (wanted.has(hash)) {
          const obj = readptr(node.add(0x10)), vt = readptr(obj), slots = [];
          for (let j = 0; j < 24; j++) {
            const guest = readptr(vt.add(j * 8)).toUInt32(), host = resolve(guest);
            slots.push({slot: j, guest: '0x' + guest.toString(16), host: host ? host.toString() : null});
          }
          wanted.set(hash, {name: wanted.get(hash).name, found: true, object: obj.toString(), vtable: vt.toString(),
            rect: [0xe0,0xe4,0xe8,0xec].map(o => gm.add(obj).add(o).readFloat()), slots});
        }
        node = readptr(node);
      }
    }
    const after = gm.add(map).add(4).readU32();
    return {count_before: before, count_after: after, stable_count: before === after,
      mask, visited, elapsed_ms: Date.now() - start, objects: Array.from(wanted.values())};
  },
  watch(guests, keyboard, svc) {
    const seen = new Set();
    for (const g of guests) {
      const f = resolve(g), k = f ? f.toString() : 'null:' + g;
      if (seen.has(k)) continue;
      seen.add(k); hook(g);
    }
    if (keyboard) {
      listeners.push(Interceptor.attach(exe.base.add(P.keymap), {onEnter(args) {
        send({event: 'host_keymap', scancode: args[0].toUInt32(), thread: this.threadId, time_ms: Date.now()});
      }}));
    }
    if (svc) {
      const st = stats.snx_svc = {calls: 0, errors: 0, threads: {}, samples: []};
      const sampledThreads = new Set();
      listeners.push(Interceptor.attach(exe.base.add(P.snx_svc), {onEnter(args) {
        st.calls++;
        const tid = String(this.threadId);
        st.threads[tid] = (st.threads[tid] || 0) + 1;
        if (sampledThreads.has(tid) || st.samples.length >= P.samples) return;
        sampledThreads.add(tid);
        try { st.samples.push(cpuRecord(args[0], args[0].add(0x100).readPointer(), this.context)); }
        catch (err) { st.errors++; send({event: 'callback_error', target: 'snx_svc', error: err.message}); }
      }}));
    }
    return {event: 'ready', stats, hooks: listeners.length};
  },
  counts() { return stats; },
  read(address, size) {
    if (size < 0 || size > 20000000) throw new Error('Read bound exceeded');
    return gm.add(ptr(address)).readByteArray(size);
  }
};
"""


def fnv1a64(name: str) -> str:
    value = 0xCBF29CE484222325
    for byte in name.lower().encode('utf-8'):
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--guest', type=lambda x: int(x, 0), action='append', default=[])
    parser.add_argument('--name', action='append', default=[])
    parser.add_argument('--object', type=lambda x: int(x, 0), help='Filter GuestFn samples by the actual guest x0 object')
    parser.add_argument('--slots', help='Comma-separated slots of the first found named object to observe')
    parser.add_argument('--keyboard', action='store_true', help='Observe existing host keymap calls; never inject keys')
    parser.add_argument('--svc', action='store_true', help='Observe guest CPU and thread identities at the host SVC gate')
    parser.add_argument('--dump', action='store_true', help='Save runtime segments beside the JSON')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--g-mem', type=lambda x: int(x, 0), default=0x17AEF20)
    parser.add_argument('--g-disp', type=lambda x: int(x, 0), default=0x12910E0)
    parser.add_argument('--g-code-lo', type=lambda x: int(x, 0), default=0x17AF028)
    parser.add_argument('--g-code-hi', type=lambda x: int(x, 0), default=0x17AF030)
    parser.add_argument('--keymap', type=lambda x: int(x, 0), default=0x96B70)
    parser.add_argument('--snx-svc', type=lambda x: int(x, 0), default=0x17DF80)
    parser.add_argument('--expected-runtime-sha256', default='f64723c0d627cd91e553fc739f042136b5d3004397b3b8148ec53294140458a7',
                        help='Expected runtime fingerprint; update explicitly after rederiving all RVAs')
    args = parser.parse_args()
    if not 0 <= args.seconds <= 60 or not 1 <= args.samples <= 10:
        parser.error('Use 0..60 seconds and 1..10 samples per hook')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {'pid': args.pid, 'started_utc': datetime.now(timezone.utc).isoformat(), 'events': []}
    session = frida.get_local_device().attach(args.pid)
    disconnected = threading.Event()
    session.on('detached', lambda *_: disconnected.set())
    payload = {k: getattr(args, k) for k in ('g_mem', 'g_disp', 'g_code_lo', 'g_code_hi', 'keymap', 'snx_svc', 'samples')}
    payload['object_filter'] = args.object
    result['rvas_and_sample_limit'] = payload
    script = session.create_script(JS.replace('PAYLOAD', json.dumps(payload)))

    def on_message(message, data):
        event = message.get('payload', message)
        result['events'].append(event)
        if message.get('type') == 'error' or (isinstance(event, dict) and event.get('event') in ('host_keymap', 'callback_error')):
            print(json.dumps(event), flush=True)

    script.on('message', on_message)
    started = time.perf_counter()
    try:
        script.load()
        api = script.exports_sync
        result['runtime'] = api.info()
        result['hashes'] = {}
        for key in ('exe', 'code_dll'):
            with Path(result['runtime'][key]).open('rb') as source:
                result['hashes'][key] = hashlib.file_digest(source, 'sha256').hexdigest()
        if result['hashes']['exe'] != args.expected_runtime_sha256.lower():
            raise RuntimeError('Runtime hash changed; rederive every RVA before overriding the expected SHA-256')
        if args.name:
            result['registry'] = api.snapshot([{'name': n, 'hash': fnv1a64(n)} for n in args.name])
            print('REGISTRY', json.dumps(result['registry']), flush=True)
        guests = list(args.guest)
        if args.slots:
            obj = next(o for o in result['registry']['objects'] if o['found'])
            guests.extend(int(obj['slots'][int(i)]['guest'], 0) for i in args.slots.split(','))
        if args.dump:
            mainmod = next(m for m in result['runtime']['modules'] if m['name'] == 'main')
            result['segments'] = {}
            for seg in ('text', 'ro', 'data'):
                blob = api.read(hex(int(mainmod['base'], 0) + mainmod[seg + '_off']), mainmod[seg + '_size'])
                dest = args.out.with_name(args.out.stem + '_' + seg + '.bin')
                dest.write_bytes(blob)
                result['segments'][seg] = {'path': str(dest.resolve()), 'sha256': hashlib.sha256(blob).hexdigest(),
                    'base': int(mainmod['base'], 0) + mainmod[seg + '_off'], 'size': len(blob)}
        if guests or args.keyboard or args.svc:
            print('READY', json.dumps(api.watch(guests, args.keyboard, args.svc)), flush=True)
            disconnected.wait(args.seconds)
            result['counts'] = api.counts() if not disconnected.is_set() else None
            result['disconnected'] = disconnected.is_set()
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        result['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('SAVED', str(args.out), 'elapsed', result['elapsed_seconds'], flush=True)


if __name__ == '__main__':
    main()
