#!/usr/bin/env python3
"""Find float fields in the main module's .data/.bss that track the local player's world position.

Reads the region twice (before/after a short walk driven by a real W key) and reports
addresses where 32-bit floats changed by a small amount.  Entity objects keep their id
in the first word and x/y/z at +0x60/0x64/0x68, so a hit is a candidate for either the
player entity or the camera target that follows it.

A candidate is not proof of player identity: the camera target eases toward the player,
so a short walk also surfaces camera-smoothing floats, and this scan cannot tell the
player entity from camera state.  Confirm with an independent read (entity handle,
before/after position, and a second walk).

The module range comes from ``out/windows/kbm/b2/runtime_info.json`` when that ignored
file exists; otherwise the whole main module (``exe.base`` .. ``exe.size``) is scanned,
so the probe still runs on a clean checkout.  The key press helper lives in
``windows/tools/Real-Input.ps1`` and is not taken from ``out/``.

Usage:
  python windows/d3-re/probe_player_scan.py --pid <pid> --seconds 2
  python windows/d3-re/probe_player_scan.py --pid <pid> --key w --hold-ms 2000
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import frida

from version import assert_installed, js_consts

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INFO = ROOT / "out/windows/kbm/b2/runtime_info.json"
DEFAULT_INPUT = ROOT / "windows/tools/Real-Input.ps1"


def module_region(info_path: Path) -> tuple[int, int] | None:
    """The guest .data+.bss range, when the ignored runtime dump is present."""
    if not info_path.exists():
        return None
    info = json.loads(info_path.read_text(encoding="utf-8"))["main"]
    start = int(info["base"], 0) + int(info["data_off"])
    size = (int(info["data_size"]) + int(info["bss_size"])) & ~3  # Float32Array needs whole words
    return start, size


def build_js(region: tuple[int, int] | None) -> str:
    if region is None:
        # exe.size covers the mapped image, including .bss; text and rodata are included
        # too, which only adds noise that the change filter drops.
        where = "const START = exe.base;\nconst SIZE = exe.size & ~3;"
    else:
        where = f"const START = 0x{region[0]:x};\nconst SIZE = 0x{region[1]:x};"
    return (
        js_consts()
        + where
        + """
function snap() {
  const out = new Uint8Array(SIZE);
  const CH = 1 << 20;
  for (let o = 0; o < SIZE; o += CH) {
    const n = Math.min(CH, SIZE - o);
    out.set(new Uint8Array(gm.add(START + o).readByteArray(n)), o);
  }
  return out;
}
const a = snap();
send({ ready: true, start: START, bytes: SIZE });
rpc.exports = {
  diff: function () {
    const b = snap();
    const f = new Float32Array(a.buffer), g = new Float32Array(b.buffer);
    const hits = [];
    for (let i = 0; i < f.length; i++) {
      const x = f[i], y = g[i];
      if (!isFinite(x) || !isFinite(y)) continue;
      const d = Math.abs(y - x);
      if (d > 0.005 && d < 60 && Math.abs(y) < 5000) {
        hits.push([START + i * 4, x, y]);
      }
    }
    return hits;
  }
};
"""
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=2.0,
                    help="walk time; ignored with --hold-ms")
    ap.add_argument("--hold-ms", type=int, default=None, help="key hold time in milliseconds")
    ap.add_argument("--key", default="w", help="key to hold during the walk (default w)")
    ap.add_argument("--input-script", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--runtime-info", type=Path, default=DEFAULT_INFO)
    ap.add_argument("--out", default="out/windows/kbm/round9/player-scan.json")
    args = ap.parse_args()
    hold_ms = args.hold_ms if args.hold_ms is not None else int(args.seconds * 1000)

    region = module_region(args.runtime_info)
    if region is None:
        print(f"{args.runtime_info} not found; scanning the whole main module")
    assert_installed()
    session = frida.get_local_device().attach(args.pid)
    script = session.create_script(build_js(region))
    ready = {"v": False}

    def on_message(message, _data):
        payload = message.get("payload", message)
        if isinstance(payload, dict) and payload.get("ready"):
            ready["v"] = True
            print(f"snapshot 0x{payload['start']:x}, {payload['bytes']} bytes", flush=True)
        else:
            print(payload, flush=True)

    script.on("message", on_message)
    script.load()
    for _ in range(600):
        if ready["v"]:
            break
        time.sleep(0.1)
    if not ready["v"]:
        session.detach()
        raise SystemExit("snapshot did not become ready")

    # Walk with a real key: the engine's own input path moves the player, not a probe write.
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(args.input_script), "-Key", args.key, "-HoldMs", str(hold_ms)],
                       check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        session.detach()
        raise SystemExit(f"walk failed (is the game window focused?): {exc}")
    time.sleep(0.4)
    hits = script.exports_sync.diff()
    session.detach()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(hits, indent=1), encoding="utf-8")
    print(f"{len(hits)} float(s) changed; first 40:")
    for addr, x, y in hits[:40]:
        print(f"  0x{addr:08x}  {x:.3f} -> {y:.3f}  (d={y - x:+.3f})")


if __name__ == "__main__":
    main()
