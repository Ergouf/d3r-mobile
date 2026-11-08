"""Drive one scripted sequence inside a single Frida attach.

Each action runs in order: SDL key down/up, SDL pointer click (engine 1280x720
coordinates, no OS focus or real cursor), or a sleep.  Sleeps are paced from
the controlling Python process, never inside the Frida JS callback, so the game
thread is not blocked.  After the sequence the script returns the visible UI
text, the runtime state and the recent log tail, so one attach can cover a whole
map/portal interaction instead of one attach per probe.

The output JSON keeps the original keys (build/actions/state/ui).  Every entry
in "actions" is in executed order and records its 0-based index, kind, sequence
offset and wall-clock elapsed time; sleep entries also record how many bounded
(<=30 s) chunks were used.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

import frida
import psutil

import version
import probe_ui_tree

KEYS = {
    "ctrl": (224, 0x400000E0), "esc": (41, 27), "backspace": (42, 8),
    "tab": (43, 9), "space": (44, 32), "enter": (40, 13),
    "f2": (59, 0x4000003B), "f3": (60, 0x4000003C),
    "f4": (61, 0x4000003D), "f5": (62, 0x4000003E), "f6": (63, 0x4000003F),
    "f7": (64, 0x40000040), "f8": (65, 0x40000041), "f9": (66, 0x40000042),
    "f10": (67, 0x40000043),
    "home": (74, 0x4000004A), "end": (77, 0x4000004D),
    "insert": (73, 0x40000049), "delete": (76, 0x4000004C),
    "pageup": (75, 0x4000004B), "pagedown": (78, 0x4000004E),
    "minus": (45, 45), "equals": (46, 61),
    "shift": (225, 0x400000E1), "alt": (226, 0x400000E2),
    "right": (79, 0x4000004F), "left": (80, 0x40000050),
    "down": (81, 0x40000051), "up": (82, 0x40000052),
    **{ch: (4 + i, ord(ch)) for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{str(i): (29 + i, ord(str(i))) for i in range(1, 10)},
    "0": (39, ord("0")),
}

SLEEP_CHUNK_S = 30.0

DRIVER_JS = r"""
rpc.exports.drive = function(actions) {
  const win = base.add(RVA.sdl_window).readPointer();
  if (win.isNull()) throw new Error('SDL window missing');
  const size = Memory.alloc(8);
  const getSize = new NativeFunction(base.add(RVA.sdl_get_window_size), 'bool',
                                    ['pointer', 'pointer', 'pointer']);
  if (!getSize(win, size, size.add(4))) throw new Error('SDL window size unavailable');
  const width = size.readS32(), height = size.add(4).readS32();
  const density = new NativeFunction(base.add(RVA.sdl_pixel_density), 'float', ['pointer'])(win);
  const getId = new NativeFunction(base.add(RVA.sdl_get_window_id), 'uint', ['pointer']);
  const id = getId(win);
  const push = new NativeFunction(base.add(RVA.sdl_push_event), 'bool', ['pointer']);
  function keyEvent(scan, code, down, mod) {
    const ev = Memory.alloc(128);
    ev.writeByteArray(new Uint8Array(128));
    ev.writeU32(down ? 0x300 : 0x301);
    ev.add(16).writeU32(id);
    ev.add(24).writeU32(scan);
    ev.add(28).writeU32(code);
    ev.add(32).writeU16(mod);
    ev.add(36).writeU8(down ? 1 : 0);
    return push(ev);
  }
  const out = [];
  for (const a of actions) {
    if (a.drag) {
      const safe = Memory.alloc(16);
      new NativeFunction(base.add(RVA.backend_window_safe), 'void',
                         ['pointer', 'pointer', 'pointer', 'pointer'])(
                           safe, safe.add(4), safe.add(8), safe.add(12));
      const area = [0,4,8,12].map(o => safe.add(o).readS32());
      let dw = area[2], dh = Math.floor(dw * 720 / 1280);
      if (dh > area[3]) { dh = area[3]; dw = Math.floor(dh * 1280 / 720); }
      const dx = area[0] + Math.floor((area[2] - dw) / 2);
      const dy = area[1] + Math.floor((area[3] - dh) / 2);
      const points = [[a.drag[0], a.drag[1]], [a.drag[2], a.drag[3]]].map(([x,y]) =>
        [(dx + x * dw / 1280.0) / density, (dy + y * dh / 720.0) / density]);
      const res = [];
      for (let phase = 0; phase < 3; phase++) {
        const ev = Memory.alloc(128);
        ev.writeByteArray(new Uint8Array(128));
        const point = points[phase === 0 ? 0 : 1];
        if (phase === 1) {
          ev.writeU32(0x400);
          ev.add(16).writeU32(id); ev.add(20).writeU32(1); ev.add(24).writeU32(1);
          ev.add(28).writeFloat(point[0]); ev.add(32).writeFloat(point[1]);
        } else {
          ev.writeU32(phase === 0 ? 0x401 : 0x402);
          ev.add(16).writeU32(id); ev.add(24).writeU8(1);
          ev.add(25).writeU8(phase === 0 ? 1 : 0); ev.add(26).writeU8(1);
          ev.add(28).writeFloat(point[0]); ev.add(32).writeFloat(point[1]);
        }
        res.push(push(ev));
      }
      out.push({drag: a.drag, logicalPixel: points, pushed: res});
    } else if (a.wheel) {
      const ev = Memory.alloc(128);
      ev.writeByteArray(new Uint8Array(128));
      ev.writeU32(0x403);
      ev.add(16).writeU32(id);
      ev.add(24).writeFloat(a.wheel[0]);
      ev.add(28).writeFloat(a.wheel[1]);
      ev.add(32).writeU32(0);
      ev.add(44).writeS32(Math.trunc(a.wheel[0]));
      ev.add(48).writeS32(Math.trunc(a.wheel[1]));
      out.push({wheel: a.wheel, pushed: push(ev)});
    } else if (a.move) {
      // Queue a pointer position without synthesizing a button press. This
      // mirrors probe_pointer_move and lets a following skill key resolve the
      // live world target from the same attach.
      const safe = Memory.alloc(16);
      new NativeFunction(base.add(RVA.backend_window_safe), 'void',
                         ['pointer', 'pointer', 'pointer', 'pointer'])(
                           safe, safe.add(4), safe.add(8), safe.add(12));
      const area = [0,4,8,12].map(o => safe.add(o).readS32());
      if (!(density > 0 && area[2] > 0 && area[3] > 0)) throw new Error('invalid safe area');
      let dw = area[2], dh = Math.floor(dw * 720 / 1280);
      if (dh > area[3]) { dh = area[3]; dw = Math.floor(dh * 1280 / 720); }
      const dx = area[0] + Math.floor((area[2] - dw) / 2);
      const dy = area[1] + Math.floor((area[3] - dh) / 2);
      const fx = dx + a.move[0] * dw / 1280.0, fy = dy + a.move[1] * dh / 720.0;
      const ev = Memory.alloc(128);
      ev.writeByteArray(new Uint8Array(128));
      ev.writeU32(0x400);
      ev.add(16).writeU32(id);
      ev.add(20).writeU32(1);
      ev.add(28).writeFloat(fx / density);
      ev.add(32).writeFloat(fy / density);
      out.push({move: a.move, window: [width, height],
                pictureRect: [dx, dy, dw, dh], logicalPixel: [fx / density, fy / density],
                pixelDensity: density, pushed: [push(ev)]});
    } else if (a.click) {
      // Match probe_pointer_click and the production letterboxed viewport.
      const safe = Memory.alloc(16);
      new NativeFunction(base.add(RVA.backend_window_safe), 'void',
                         ['pointer', 'pointer', 'pointer', 'pointer'])(
                           safe, safe.add(4), safe.add(8), safe.add(12));
      const area = [0,4,8,12].map(o => safe.add(o).readS32());
      if (!(density > 0 && area[2] > 0 && area[3] > 0)) throw new Error('invalid safe area');
      let dw = area[2], dh = Math.floor(dw * 720 / 1280);
      if (dh > area[3]) { dh = area[3]; dw = Math.floor(dh * 1280 / 720); }
      const dx = area[0] + Math.floor((area[2] - dw) / 2);
      const dy = area[1] + Math.floor((area[3] - dh) / 2);
      const fx = dx + a.click[0] * dw / 1280.0, fy = dy + a.click[1] * dh / 720.0;
      const res = [];
      const modifiers = [];
      if (a.ctrl) modifiers.push([224, 0x400000E0, 0x40]);
      if (a.shift) modifiers.push([225, 0x400000E1, 1]);
      if (a.alt) modifiers.push([226, 0x400000E2, 0x100]);
      let mod = 0;
      for (const [scan, code, bit] of modifiers) {
        mod |= bit;
        res.push(keyEvent(scan, code, true, mod));
      }
      for (const down of [true, false]) {
        const ev = Memory.alloc(128);
        ev.writeByteArray(new Uint8Array(128));
        ev.writeU32(down ? 0x401 : 0x402);
        ev.add(16).writeU32(id);
        ev.add(24).writeU8(1);
        ev.add(25).writeU8(down ? 1 : 0);
        ev.add(26).writeU8(1);
        ev.add(28).writeFloat(fx / density);
        ev.add(32).writeFloat(fy / density);
        res.push(push(ev));
      }
      for (const [scan, code, bit] of modifiers.reverse()) {
        mod &= ~bit;
        res.push(keyEvent(scan, code, false, mod));
      }
      out.push({click: a.click, window: [width, height],
                pictureRect: [dx, dy, dw, dh], logicalPixel: [fx / density, fy / density],
                pixelDensity: density, shift: !!a.shift, ctrl: !!a.ctrl, alt: !!a.alt, pushed: res});
    } else if (a.key) {
      const k = a.key;
      const res = [];
      const phases = a.phase === 'down' ? [true] : a.phase === 'up' ? [false] : [true, false];
      for (const down of phases) {
        const ev = Memory.alloc(128);
        ev.writeByteArray(new Uint8Array(128));
        ev.writeU32(down ? 0x300 : 0x301);
        ev.add(16).writeU32(id);
        ev.add(24).writeU32(k.scan);
        ev.add(28).writeU32(k.code);
        ev.add(32).writeU16(a.mod | 0);
        ev.add(36).writeU8(down ? 1 : 0);
        res.push(push(ev));
      }
      out.push({key: a.key.name, pushed: res});
    }
  }
  return out;
};
rpc.exports.state = function() {
  const g = base.add(RVA.world_goal);
  const u32 = o => g.add(o).readU32();
  return {
    enabled: base.add(RVA.world_enabled).readU32(),
    ui_blocked: base.add(RVA.world_ui_blocked).readU32(),
    serial: base.add(RVA.world_serial).readU32(),
    goal: {
      active: u32(0), entity_goal: u32(4), submitted: u32(8), attack: u32(12),
      sno: u32(88), target_place: u32(56), entity_place: u32(104),
      target: [44,48,52].map(o => g.add(o).readFloat()),
      previous: [60,64,68].map(o => g.add(o).readFloat()),
    }
  };
};
"""


def _sleep_milliseconds(value: object, index: int) -> float:
    """Validate one sleep duration and return it in milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"action {index}: sleep must be milliseconds as a number, got {value!r}")
    ms = float(value)
    if not math.isfinite(ms):
        raise SystemExit(f"action {index}: sleep must be finite, got {value!r}")
    if ms < 0:
        raise SystemExit(f"action {index}: sleep must be >= 0 ms, got {ms}")
    return ms


def _sleep_ms(ms: float) -> int:
    """Wait ms milliseconds in chunks of at most SLEEP_CHUNK_S seconds."""
    remaining = ms / 1000.0
    chunks = 0
    while remaining > 0:
        step = min(remaining, SLEEP_CHUNK_S)
        time.sleep(step)
        remaining -= step
        chunks += 1
    return chunks


def _prepare(actions: list) -> list[dict]:
    """Normalize and validate actions before attaching, preserving order."""
    prepared = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise SystemExit(f"action {index}: expected an object, got {type(action).__name__}")
        if "sleep" in action or "sleep_ms" in action:
            raw = action["sleep"] if "sleep" in action else action["sleep_ms"]
            prepared.append({"type": "sleep", "index": index,
                             "sleep": _sleep_milliseconds(raw, index)})
        elif "key" in action:
            key = action["key"]
            if key not in KEYS:
                raise SystemExit("unknown key " + str(key))
            scan, code = KEYS[key]
            phase = action.get("phase")
            if phase not in (None, "down", "up", "both"):
                raise SystemExit(f"action {index}: key phase must be down, up, or both")
            ready = {"key": {"name": key, "scan": scan, "code": code},
                     "mod": 0xC0 if action.get("ctrl") else 0}
            if phase in ("down", "up"):
                ready["phase"] = phase
            prepared.append({"type": "key", "index": index, "action": ready})
        elif "drag" in action:
            drag = action["drag"]
            if (not isinstance(drag, (list, tuple)) or len(drag) != 4 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float))
                        or not math.isfinite(float(v)) for v in drag)):
                raise SystemExit(f"action {index}: drag must be [x1, y1, x2, y2] with finite numbers")
            prepared.append({"type": "drag", "index": index,
                             "action": {"drag": [float(v) for v in drag]}})
        elif "wheel" in action:
            wheel = action["wheel"]
            if (not isinstance(wheel, (list, tuple)) or len(wheel) != 2 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float))
                        or not math.isfinite(float(v)) for v in wheel)):
                raise SystemExit(f"action {index}: wheel must be [x, y] with finite numbers")
            prepared.append({"type": "wheel", "index": index,
                             "action": {"wheel": [float(wheel[0]), float(wheel[1])]}})
        elif "move" in action:
            move = action["move"]
            if (not isinstance(move, (list, tuple)) or len(move) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(float(v)) for v in move)):
                raise SystemExit(f"action {index}: move must be [x, y] with finite numbers")
            prepared.append({"type": "move", "index": index,
                             "action": {"move": [float(move[0]), float(move[1])]}})
        elif "click" in action:
            click = action["click"]
            if (not isinstance(click, (list, tuple)) or len(click) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(float(v)) for v in click)):
                raise SystemExit(f"action {index}: click must be [x, y] with finite numbers")
            ready = {k: v for k, v in action.items() if k != "sleep"}
            ready["click"] = [float(click[0]), float(click[1])]
            prepared.append({"type": "click", "index": index, "action": ready})
        else:
            raise SystemExit(f"action {index}: expected a key, click or sleep action")
    return prepared


def _process_identity(pid: int) -> dict:
    """Verify the PID is the installed game before attaching and record its identity."""
    try:
        proc = psutil.Process(pid)
        exe = proc.exe()
        create_time = proc.create_time()
    except psutil.NoSuchProcess:
        raise SystemExit(f"process {pid} does not exist; refusing to attach") from None
    except (psutil.AccessDenied, psutil.ZombieProcess, OSError) as exc:
        raise SystemExit(f"cannot inspect process {pid}: {exc}; refusing to attach") from exc
    actual = Path(exe).resolve()
    expected = Path(version.EXE).resolve()
    if os.path.normcase(str(actual)) != os.path.normcase(str(expected)):
        raise SystemExit(f"process {pid} exe mismatch: expected {expected}, found {actual}; refusing to attach")
    return {
        "pid": pid,
        "exe": str(actual),
        "expected_exe": str(expected),
        "create_time": create_time,
        "create_time_iso": datetime.datetime.fromtimestamp(create_time).astimezone().isoformat(),
        "exe_sha256": version.sha256(actual),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--actions", default="[]", help="JSON list of actions")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-ui", action="store_true")
    args = ap.parse_args()
    build = version.assert_installed()
    identity = _process_identity(args.pid)
    actions = json.loads(args.actions)
    prepared = _prepare(actions)
    session = frida.get_local_device().attach(args.pid)
    try:
        script = session.create_script(probe_ui_tree.JS + DRIVER_JS)
        script.load()
        results = []
        started = time.perf_counter()
        for step in prepared:
            step_started = time.perf_counter()
            offset_ms = (step_started - started) * 1000.0
            if step["type"] == "sleep":
                chunks = _sleep_ms(step["sleep"])
                entry = {"index": step["index"], "type": "sleep",
                         "sleep": step["sleep"], "chunks": chunks}
            else:
                sent = script.exports_sync.drive([step["action"]])
                entry = dict(sent[0]) if sent else {}
                entry["index"] = step["index"]
                entry["type"] = step["type"]
            entry["offset_ms"] = round(offset_ms, 1)
            entry["elapsed_ms"] = round((time.perf_counter() - step_started) * 1000.0, 1)
            results.append(entry)
        time.sleep(0.5)
        state = script.exports_sync.state()
        ui = None if args.no_ui else script.exports_sync.dump(None, True)
    finally:
        session.detach()
    payload = {"build": build, "identity": identity, "actions": results, "state": state, "ui": ui}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(state, indent=1))
    for entry in results:
        if entry["type"] == "sleep":
            print(f"action {entry['index']}: sleep {entry['sleep']:.0f} ms "
                  f"in {entry['chunks']} chunk(s), offset {entry['offset_ms']} ms, "
                  f"elapsed {entry['elapsed_ms']} ms")
        else:
            print(f"action {entry['index']}: {entry['type']}, offset {entry['offset_ms']} ms, "
                  f"elapsed {entry['elapsed_ms']} ms")
    if ui:
        print("visible UI:", len(ui["items"]))
        for it in ui["items"]:
            text = (it.get("text") or "").strip()
            if text:
                print(tuple(round(v) for v in it["rect2"]), text[:90].replace("\n", " | "))


if __name__ == "__main__":
    main()
