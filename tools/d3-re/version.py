"""Single source of truth for the D3 build and runtime RVAs used by probes.

Every probe imports this module, calls :func:`assert_installed` before it
attaches, and builds its JS from :func:`js_consts` instead of hardcoding
addresses.  A mismatch stops the probe instead of silently measuring a
different binary.

The anchor is the installed game, not a build directory: the build tree may
be cleaned at any time, while the installed exe is what actually runs.
"""
from __future__ import annotations

import hashlib
import json
import atexit
import os
import subprocess
from pathlib import Path

_probe_lock = None


def _acquire_probe_lock() -> None:
    """Keep all versioned probes serial, including while a shell call yields."""
    global _probe_lock
    if _probe_lock is not None:
        return
    lock_path = Path(__file__).resolve().parents[2] / "out/windows/kbm/probe.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.seek(0, 2) == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit("another KBM probe is still running; refusing concurrent attach") from None
    _probe_lock = handle
    atexit.register(handle.close)

GAME_DIR = Path(r"D:\Games\DiabloIII\01001B300B9BE000")
EXE = GAME_DIR / "01001B300B9BE000.exe"
CODE_DLL = GAME_DIR / "01001B300B9BE000_code.dll"
EXE_NAME_JS = "01001b300b9be000.exe"

# 2026-11-04 through 0039: blacksmith crafting rings, native icon highlight
# callbacks, and gated footer business actions for artisans and Kadala.
BUILD = {
    "exe_sha256": "32BC5885F48B3CF299BD4604ECB29B54B146264D50191DFE9CC0C11639314FE8",
    "code_dll_sha256": "A829DCE8AC2554A44DF087132CF9D266582010280C660D32A958642C8B7BDA51",
}

# PE RVAs relative to the module base (0x140000000 when loaded normally).
# The runtime is rebuilt for every patch stage, so hardcoded RVAs go stale as
# soon as a new exe is installed.  Resolve them from the exe's own symbol table
# instead; the table is present in every build and the names are stable.
IMAGE_BASE = 0x140000000
LLVM_NM = Path(r"D:\workspace\msys2\msys64\clang64\bin\llvm-nm.exe")

# key used by probes -> symbol in the installed exe
RVA_SYMBOLS = {
    "g_mem": "g_mem",
    "g_disp": "g_disp",
    "g_code_lo": "g_code_lo",
    "g_code_hi": "g_code_hi",
    "g_hle_ptr": ".refptr.g_hle",
    "g_hle": "g_hle",
    "keymap": "keymap",
    "snx_svc": "snx_svc",
    "kshmem_ptr": "kshmem_ptr",
    "mem_query": "mem_query",
    "kmem_alloc": "kmem_alloc",
    "mem_unmap": "mem_unmap",
    "hid_update": "hid_update",
    "native_action_press": "native_action_press",
    "native_action_cancel": "native_action_cancel",
    "native_world_click": "native_world_click",
    "native_world_cancel": "native_world_cancel",
    "world_enabled": "g_enabled",
    "world_ui_blocked": "g_ui_blocked",
    "world_goal": "g_goal",
    "world_pointer_pending": "g_have_pointer",
    "world_serial": "g_serial",
    "sdl_push_event": "SDL_PushEvent",
    "sdl_get_window_id": "SDL_GetWindowID",
    "sdl_get_window_size": "SDL_GetWindowSize",
    "sdl_pixel_density": "SDL_GetWindowPixelDensity",
    "backend_window_safe": "backend_window_safe",
    "sdl_window": "g_win",
}

# Only used when llvm-nm cannot read the exe (e.g. offline unit tests).  These
# values belong to the 0074 build and must never be used against another exe;
# _resolve_rvas() refuses instead of silently measuring the wrong addresses.
RVA_FALLBACK = {
    "g_mem": 0x17CAFE0,
    "g_disp": 0x12AD190,
    "g_code_lo": 0x17CB0E8,
    "g_code_hi": 0x17CB0F0,
    "g_hle_ptr": 0xD046D0,
    "g_hle": 0x12AEC78,
    "keymap": 0x980F0,
    "snx_svc": 0x17F760,
    "kshmem_ptr": 0x1CB580,
    "mem_query": 0x66140,
    "kmem_alloc": 0x66940,
    "mem_unmap": 0x65EA0,
    "hid_update": 0x82AB0,
    "native_action_press": 0x76300,
    "native_world_click": 0x1DECB0,
    "native_world_cancel": 0x1DEFA0,
    "world_enabled": 0x18BFD90,
    "world_ui_blocked": 0x10F14D8,
    "world_goal": 0x18C0028,
    "world_pointer_pending": 0x18BFFE0,
    "world_serial": 0x18BFDA8,
    "sdl_push_event": 0x302A0,
    "sdl_get_window_id": 0x2FA00,
    "sdl_get_window_size": 0x2FAE0,
    "sdl_pixel_density": 0x2FA80,
    "backend_window_safe": 0x93BD0,
    "sdl_window": 0x18355D0,
    "input_manager": 0x80FD4B0,
}


def _symbol_table(path: Path) -> dict[str, int]:
    """Map symbol name -> PE RVA using the build's own symbol table."""
    if not LLVM_NM.exists():
        return {}
    try:
        out = subprocess.run([str(LLVM_NM), str(path)], capture_output=True,
                             text=True, timeout=120, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3 or len(parts[1]) != 1:
            continue
        try:
            addr = int(parts[0], 16)
        except ValueError:
            continue
        if addr >= IMAGE_BASE:
            table.setdefault(parts[2], addr - IMAGE_BASE)
    return table


def _resolve_rvas() -> dict[str, int]:
    if not EXE.exists():
        return dict(RVA_FALLBACK)
    table = _symbol_table(EXE)
    if not table:
        raise RuntimeError(
            "cannot resolve runtime RVAs: llvm-nm did not report symbols for " + str(EXE))
    rva = dict(RVA_FALLBACK)
    missing = [k for k, sym in RVA_SYMBOLS.items() if sym not in table]
    if missing:
        raise RuntimeError("installed exe is missing expected runtime symbols: " + ", ".join(missing))
    for key, sym in RVA_SYMBOLS.items():
        rva[key] = table[sym]
    return rva


RVA = _resolve_rvas()

# HleHid field offsets (relative to the HleHid* in g_hle_ptr).
HLE = {
    "pad_buttons": 0x2C89E0,   # provisional: used by the canary probe
    "mouse": 0x2C8DA4,
    "mouse_on": 0x2C8DC4,
    "input_lock": 0x2C8DC8,
    "lock": 0x2C8DD0,
    "shm": 0x2C8DD8,
    "samp": 0x2C8E48,
}

# Guest-side layout of the shared-memory block (bytes from its host base).
SHM = {
    "touch": 0x400,
    "mouse": 0x3400,
    "keyboard": 0x3800,
    "npad": 0x9A00,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def assert_installed() -> dict[str, str]:
    """Stop unless the installed exe and code dll are the expected build."""
    _acquire_probe_lock()
    missing = [str(p) for p in (EXE, CODE_DLL) if not p.exists()]
    if missing:
        raise SystemExit("missing game files: " + ", ".join(missing))
    got = {"exe_sha256": sha256(EXE), "code_dll_sha256": sha256(CODE_DLL)}
    wrong = {k: (BUILD[k], v) for k, v in got.items() if BUILD[k] != v}
    if wrong:
        detail = "; ".join(f"{k}: expected {e}, found {g}" for k, (e, g) in wrong.items())
        raise SystemExit("build mismatch, refusing to probe: " + detail)
    return got


def js_consts() -> str:
    """JS prelude with the module lookup and every RVA/HLE/SHM constant."""
    rva = ",\n  ".join(f"{k}: 0x{v:X}" for k, v in RVA.items())
    hle = ",\n  ".join(f"{k}: 0x{v:X}" for k, v in HLE.items())
    shm = ",\n  ".join(f"{k}: 0x{v:X}" for k, v in SHM.items())
    return f"""
const exe = Process.enumerateModules().find(m => m.name.toLowerCase() === '{EXE_NAME_JS}');
if (!exe) throw new Error('game module not found');
const normalizePath = s => s.split(String.fromCharCode(92)).join('/').toLowerCase();
if (normalizePath(exe.path) !== {json.dumps(EXE.as_posix().lower())})
  throw new Error('target PID loaded an executable from a different path: ' + exe.path);
const guestModule = Process.enumerateModules().find(m => m.name.toLowerCase() === {json.dumps(CODE_DLL.name.lower())});
if (!guestModule || normalizePath(guestModule.path) !== {json.dumps(CODE_DLL.as_posix().lower())})
  throw new Error('target PID code DLL path does not match the validated installation');
const base = exe.base;
const RVA = {{
  {rva}
}};
const HLE = {{
  {hle}
}};
const SHM = {{
  {shm}
}};
const gm = base.add(RVA.g_mem).readPointer();
const disp = base.add(RVA.g_disp).readPointer();
const codeLo = base.add(RVA.g_code_lo).readU64().toNumber();
const codeHi = base.add(RVA.g_code_hi).readU64().toNumber();
function resolveGuest(g) {{
  if (g < codeLo || g >= codeHi || (g % 4)) return null;
  const f = disp.add(((g - codeLo) / 4) * 8).readPointer();
  return f.isNull() ? null : f;
}}
function hexBytes(guest, n) {{
  try {{
    return Array.from(new Uint8Array(gm.add(ptr(guest)).readByteArray(n)),
                      b => b.toString(16).padStart(2, '0')).join('');
  }} catch (e) {{ return 'err:' + e.message; }}
}}
"""
