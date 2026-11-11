"""Bind probe hashes and host RVAs to the exact freshly linked executable."""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = {
    "g_mem":"g_mem", "g_disp":"g_disp", "g_code_lo":"g_code_lo", "g_code_hi":"g_code_hi",
    "g_hle_ptr":".refptr.g_hle", "g_hle":"g_hle", "keymap":"keymap", "snx_svc":"snx_svc",
    "kshmem_ptr":"kshmem_ptr", "mem_query":"mem_query", "kmem_alloc":"kmem_alloc",
    "mem_unmap":"mem_unmap", "hid_update":"hid_update", "native_action_press":"native_action_press",
    "native_world_click":"native_world_click", "native_world_cancel":"native_world_cancel",
    "world_enabled":"g_enabled", "world_ui_blocked":"g_ui_blocked", "world_goal":"g_goal",
    "world_pointer_pending":"g_have_pointer", "world_serial":"g_serial",
    "sdl_push_event":"SDL_PushEvent", "sdl_get_window_id":"SDL_GetWindowID",
    "sdl_get_window_size":"SDL_GetWindowSize", "sdl_pixel_density":"SDL_GetWindowPixelDensity",
    "backend_window_safe":"backend_window_safe", "sdl_window":"g_win",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe",type=Path,default=ROOT/"out/windows/build-kbm/scarletnx.exe")
    ap.add_argument("--nm",default="D:/workspace/msys2/msys64/clang64/bin/llvm-nm.exe")
    args = ap.parse_args()
    version = ROOT/"windows/d3-re/version.py"
    source = version.read_text("utf-8")
    nm = subprocess.check_output([args.nm,"--defined-only",str(args.exe)],text=True)
    symbols: dict[str,list[int]] = {}
    for line in nm.splitlines():
        fields = line.split()
        if len(fields)==3:
            symbols.setdefault(fields[2],[]).append(int(fields[0],16)-0x140000000)
    for key,name in SYMBOLS.items():
        matches = symbols.get(name,[])
        if len(matches)!=1:
            raise RuntimeError(f"{name}: expected one definition, found {matches}")
        source,count = re.subn(r'("'+key+r'"\s*:\s*)0x[0-9a-fA-F]+',
            lambda m:m[1]+f"0x{matches[0]:X}",source)
        if count!=1:
            raise RuntimeError(f"{key}: expected one version field, found {count}")
    digest = hashlib.sha256(args.exe.read_bytes()).hexdigest().upper()
    source,count = re.subn(r'("exe_sha256"\s*:\s*")[A-Z0-9_]+"',
        lambda m:m[1]+digest+'"',source)
    if count!=1:
        raise RuntimeError("expected one executable hash")
    version.write_text(source,"utf-8",newline="\n")
    print(f"Bound {len(SYMBOLS)} RVAs; SHA256 {digest}")


if __name__ == "__main__":
    main()
