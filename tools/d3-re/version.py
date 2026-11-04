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
from pathlib import Path

GAME_DIR = Path(r"D:\Games\DiabloIII\01001B300B9BE000")
EXE = GAME_DIR / "01001B300B9BE000.exe"
CODE_DLL = GAME_DIR / "01001B300B9BE000_code.dll"
EXE_NAME_JS = "01001b300b9be000.exe"

# 2026-11-03 build with native pointer projection, client world movement,
# actor picking / native operate and equipment-icon selection.
BUILD = {
    "exe_sha256": "F4BF82B64BF2AD1A6B5B7DD0528163820CC3BE0A5979BFFE822C405B23535714",
    "code_dll_sha256": "A829DCE8AC2554A44DF087132CF9D266582010280C660D32A958642C8B7BDA51",
}

# PE RVAs relative to the module base (0x140000000 when loaded normally).
RVA = {
    # runtime globals / dispatch
    "g_mem": 0x17BDFE0,        # guest-memory translation table base
    "g_disp": 0x12A0190,       # guest->host dispatch table (4-byte aligned slots)
    "g_code_lo": 0x17BE0E8,
    "g_code_hi": 0x17BE0F0,
    "g_hle_ptr": 0xCF86D0,     # .refptr.g_hle
    "g_hle": 0x12A1C78,
    "keymap": 0x97600,
    "snx_svc": 0x17EC60,
    "kshmem_ptr": 0x1CAA80,
    "mem_query": 0x66140,
    "kmem_alloc": 0x66940,
    "mem_unmap": 0x65EA0,
    "hid_update": 0x82AB0,     # runtime HID sampler entry (Npad publishing path)
    "native_action_press": 0x76300,
    "native_world_click": 0x1DE150,
    "native_world_cancel": 0x1DE2B0,
    "world_enabled": 0x18B2D60,
    "world_ui_blocked": 0x10E44D8,
    "world_goal": 0x18B2DB8,
    "world_pointer_pending": 0x18B2D98,
    "world_serial": 0x18B2D70,
    "sdl_push_event": 0x302A0,
    "sdl_get_window_id": 0x2FA00,
    "sdl_get_window_size": 0x2FAE0,
    "sdl_pixel_density": 0x2FA80,
    "backend_window_safe": 0x93BD0,
    "sdl_window": 0x18285D0,
    # engine
    "input_manager": 0x80FD4B0,  # method entry; 0x80FD500 is an internal block
}

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
