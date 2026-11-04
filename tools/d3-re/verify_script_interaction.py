"""Capture one SDL click with same-process before/after scene, command and UI evidence.

Only script probes are used. A command being accepted is reported separately
from a place change or UI change. This script never moves or focuses a window.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import frida

import probe_click_interact
import probe_interact_flow
import probe_pointer_click
import probe_runtime_state
import probe_ui_snapshot
import probe_world_move
from version import GAME_DIR, assert_installed


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity(pid: int) -> dict:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise RuntimeError("cannot read process identity")
    try:
        times = [ctypes.c_uint64() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in times)):
            raise RuntimeError("cannot read process start time")
        return {"pid": pid, "process_start_ticks": times[0].value}
    finally:
        kernel.CloseHandle(handle)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--target", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--screen", help="optional engine pixel x,y; otherwise midpoint of fresh target projection")
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if not 2 <= args.seconds <= 30:
        ap.error("seconds must be between 2 and 30")
    build = assert_installed()
    process = identity(args.pid)
    device = frida.get_local_device()
    if not any(p.pid == args.pid and p.name.lower() == "01001b300b9be000.exe"
               for p in device.enumerate_processes()):
        raise SystemExit("expected game PID is not running")
    report = {"build": build, **process, "started_at": utc(), "input_transport": "SDL event injection"}
    errors = []
    session = device.attach(args.pid)
    scripts = []
    flow = movement = None

    def load(source: str):
        script = session.create_script(source)
        script.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        script.load()
        scripts.append(script)
        return script.exports_sync

    log = GAME_DIR / "01001B300B9BE000.log"
    log_start = log.stat().st_size if log.exists() else 0
    try:
        # UI consumes the primary event before GAME_PC when a dialog opens.
        # The UI event still completes, so scene reads remain available there.
        scene = load(probe_click_interact.build_js(0x150030E60).replace(
            "const FRAME = 0x804f9c0;", "const FRAME = 0x8331490;"))
        runtime = load(probe_runtime_state.JS)
        pointer = load(probe_pointer_click.JS)
        ui = load(probe_ui_snapshot.JS)

        def scan():
            scene.arm({"mode": "scan", "radius": 160, "top": 2.0})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                data = scene.result()
                if data.get("result") is not None:
                    if not data["result"].get("ok"):
                        raise RuntimeError("scene scan failed: " + json.dumps(data))
                    return {"at": utc(), **data}
                time.sleep(0.05)
            raise RuntimeError("scene scan timed out")

        report["before"] = scan()
        report["runtime_before"] = runtime.read()
        if report["runtime_before"]["ui_blocked"]:
            raise RuntimeError("world click refused while UI is active")
        before = report["before"]["result"]
        targets = [e for e in before["entities"] if int(e["id"], 16) == args.target
                   and e["place"] == before["place"] and e["projOk"]]
        if len(targets) != 1:
            raise RuntimeError("fresh same-place target is absent or ambiguous")
        target = targets[0]
        pixel = ([float(v) for v in args.screen.split(",")] if args.screen else
                 [(a + b) / 2 for a, b in zip(target["screen"], target["head"])])
        if len(pixel) != 2 or not (0 <= pixel[0] < 1280 and 0 <= pixel[1] < 720):
            raise RuntimeError("fresh target projection is outside the viewport")
        report["target"] = target
        flow = load(probe_interact_flow.JS.replace("const businessOnly=false;", "const businessOnly=true;"))
        movement = load(probe_world_move.JS)
        names = probe_ui_snapshot.names_for("conversation|questlore|dialog|talk|pause|hud")
        report["ui_before"] = ui.snapshot(names, False)
        report["clicked_at"] = utc()
        report["click"] = pointer.click(*pixel, 1280, 720)
        if not report["click"]["down"] or not report["click"]["up"]:
            raise RuntimeError("SDL down/up was not queued")
        started = time.monotonic()
        report["scenes"], report["ui"] = [], []
        previous_ui = None
        changed_at = None
        while time.monotonic() - started < args.seconds:
            snap = scan()
            report["scenes"].append(snap)
            current_ui = ui.snapshot(names, False)
            signature = json.dumps(current_ui, sort_keys=True)
            if signature != previous_ui:
                report["ui"].append({"at": utc(), **current_ui})
                previous_ui = signature
            if snap["result"]["place"] != before["place"]:
                if changed_at is None:
                    changed_at = time.monotonic()
                if time.monotonic() - changed_at >= 2:
                    break
            time.sleep(0.35)
        report["flow"] = flow.stop()
        report["movement"] = movement.stop()
        report["runtime_after"] = runtime.read()
        report["after"] = scan()
        report["ui_after"] = ui.snapshot(names, False)
    except Exception as exc:
        report["failure"] = str(exc)
    finally:
        for name, observer in (("flow", flow), ("movement", movement)):
            if observer is not None and name not in report:
                try:
                    report[name] = observer.stop()
                except Exception as exc:
                    errors.append({"observer": name, "error": str(exc)})
        session.detach()
    report["errors"] = errors
    report["finished_at"] = utc()
    try:
        report["process_identity_unchanged"] = identity(args.pid) == process
    except Exception as exc:
        report["process_identity_unchanged"] = False
        report["failure"] = str(exc)
    if log.exists():
        with log.open("rb") as fh:
            fh.seek(log_start)
            report["log_delta"] = fh.read().decode("utf-8", errors="replace")
    samples = report.get("movement", {}).get("samples", [])
    calls = report.get("flow", {}).get("calls", [])
    report["summary"] = {
        "place_before": report.get("before", {}).get("result", {}).get("place"),
        "place_after": report.get("after", {}).get("result", {}).get("place"),
        "expected_target": hex(args.target),
        "native_action_count": report.get("flow", {}).get("counts", {}).get("native_action", 0),
        "command_counts": report.get("flow", {}).get("counts", {}),
        "commands": [c for c in calls if c["name"] in ("action", "prepare", "submit")],
        "neutral_npad": bool(samples) and all(s["axis"] == [0, 0] and s["buttons"] == "0" for s in samples),
        "neutral_engine": bool(samples) and all(s["engine"] == [0, 0] and s["nativeBits"] == 0 for s in samples),
        "sample_count": len(samples),
        "observer_errors": report.get("movement", {}).get("errors", []) + report.get("flow", {}).get("errors", []) + errors,
    }
    report["summary"]["place_changed"] = ("after" in report and
        report["summary"]["place_before"] != report["summary"]["place_after"])
    if report["summary"]["observer_errors"]:
        report.setdefault("failure", "interaction collection reported observer errors")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    print(json.dumps({k: v for k, v in report["summary"].items() if k != "commands"}, indent=2))
    if "failure" in report:
        print(report["failure"])
    return 1 if report.get("failure") or not report["process_identity_unchanged"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
