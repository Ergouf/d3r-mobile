"""Persist and restore the live D3 session used by the desktop harness.

The game process owns all guest handles and TLS contexts; none of those values
are stable across a restart.  This file therefore records both the observations
and an explicit staleness warning.  ``snapshot`` runs the existing probes one
at a time (concurrent Frida attachments have crashed the game) and merges the
result with a human-readable last action.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from version import BUILD, CODE_DLL, EXE, sha256

ROOT = Path(__file__).resolve().parents[2]
SESSION_DIR = ROOT / "out" / "windows" / "kbm" / "session"
SESSION_FILE = SESSION_DIR / "last_session.json"
QUICK_RESUME_FILE = SESSION_DIR / "quick-resume.json"
DEFAULT_RADIUS = 60


class FILETIME(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def process_start_ticks(pid: int) -> int | None:
    """Return the Windows process creation time in 100 ns units, if any."""
    if pid <= 0:
        return None
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created, exited, kernel, user = (FILETIME(), FILETIME(), FILETIME(), FILETIME())
        if not ctypes.windll.kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited),
                ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return (created.high << 32) | created.low
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    return process_start_ticks(pid) is not None


def window_for_pid(pid: int) -> dict | None:
    """Best-effort visible top-level window for a PID (no UI automation)."""
    user32 = ctypes.windll.user32
    found = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        owner = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        found.append({
            "hwnd": int(hwnd),
            "title": title.value,
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
        })
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        return None
    return max(found, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_probe(args: list[str], json_path: Path | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=45,
    )
    if proc.returncode:
        raise SystemExit(f"probe failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr}")
    if json_path is not None:
        return read_json(json_path)
    try:
        return json.JSONDecoder().raw_decode(proc.stdout.lstrip())[0]
    except json.JSONDecodeError as exc:
        raise SystemExit(f"probe emitted non-JSON output: {' '.join(args)}\n{proc.stdout[:2000]}") from exc


def snapshot(pid: int, radius: int, note: str, ui_state: str, place_name: str | None, place_name_source: str) -> dict:
    if not process_alive(pid):
        raise SystemExit(f"PID {pid} is not running")
    scene_path = SESSION_DIR / "scene-current.json"
    state_path = SESSION_DIR / "runtime-current.json"
    scene = run_probe(["tools/d3-re/probe_click_interact.py", "--pid", str(pid),
                       "--radius", str(radius), "--out", str(scene_path)], scene_path)
    state = run_probe(["tools/d3-re/probe_runtime_state.py", "--pid", str(pid)])
    write_json(state_path, state)
    result = scene.get("result", {})
    entities = [e for e in result.get("entities", [])
                if e.get("cap", -1) >= 0 or e.get("kind", -1) >= 0]
    data = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
        "process_start_ticks": process_start_ticks(pid),
        "window": window_for_pid(pid),
        "ui_state": ui_state,
        "place_name": place_name,
        "place_name_source": place_name_source,
        "coordinate_spaces": {
            "player_pos": "world coordinates",
            "window_rect": "DPI-virtualized GetWindowRect pixels",
            "nearby_screen": "probe engine/UI projection; may exceed window height; never add to window.rect directly",
        },
        "build": result.get("build") or state.get("build") or {},
        "player": {
            "pos": result.get("pos"),
            "place": result.get("place"),
            "context": result.get("ctx"),
            "actor": result.get("actor"),
            "entity": result.get("entity"),
            "controller": result.get("controller"),
        },
        "runtime": state,
        "nearby": entities[:24],
        "last_action": note.strip(),
        "staleness_warning": "PID, TLS context, actor/entity handles and window handles are invalid after any game restart, new game, or level change (entity table rebuild); rerun snapshot before acting.",
        "probe_policy": "Run Frida probes one at a time; concurrent attachments crashed a prior process.",
        "quick_resume": read_json(QUICK_RESUME_FILE) if QUICK_RESUME_FILE.exists() else None,
    }
    previous = {}
    if SESSION_FILE.exists():
        try:
            previous = read_json(SESSION_FILE)
        except Exception:
            previous = {}
    for key in ("active_skill", "resume_recipe", "coordinate_spaces"):
        if key in previous:
            data[key] = previous[key]
    history = list(previous.get("history", []))
    if note.strip():
        history.insert(0, {"at": data["recorded_at"], "note": note.strip(), "pid": pid})
    data["history"] = history[:30]
    write_json(SESSION_FILE, data)
    return data


def read_session() -> dict:
    if not SESSION_FILE.exists():
        raise SystemExit(f"no session memory at {SESSION_FILE}")
    data = read_json(SESSION_FILE)
    pid = int(data.get("pid") or 0)
    now_ticks = process_start_ticks(pid)
    saved_ticks = data.get("process_start_ticks")
    data["pid_alive_now"] = now_ticks is not None
    data["pid_reused_or_stale"] = bool(now_ticks is None or saved_ticks is None or now_ticks != saved_ticks)
    try:
        installed = {"exe_sha256": sha256(EXE), "code_dll_sha256": sha256(CODE_DLL)}
        data["installed_build"] = installed
        saved_build = data.get("build") or {}
        data["build_matches_installed"] = all(saved_build.get(k) == v for k, v in installed.items())
    except Exception as exc:
        data["installed_build_error"] = str(exc)
        data["build_matches_installed"] = False
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot")
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--radius", type=int, default=DEFAULT_RADIUS)
    p.add_argument("--note", default="")
    p.add_argument("--ui-state", default="unknown")
    p.add_argument("--place-name", default=None)
    p.add_argument("--place-name-source", default="user report / CUA visual; place is not a unique scene id")
    sub.add_parser("read")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        data = snapshot(args.pid, args.radius, args.note, args.ui_state, args.place_name, args.place_name_source)
        print(json.dumps({
            "saved": str(SESSION_FILE),
            "pid": data["pid"],
            "player": data["player"],
            "last_action": data["last_action"],
            "nearby_count": len(data["nearby"]),
        }, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(read_session(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
