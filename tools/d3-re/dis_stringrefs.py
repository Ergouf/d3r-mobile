#!/usr/bin/env python3
"""Annotate ADRP+ADD string references in the dumped runtime text.

Prints each string reference with the guest address of the ADRP and the next
few immediate constants, which helps identify table/registration functions.

Segment bases come from the runtime_info.json sitting next to the dumps
("main".base plus text_off/ro_off/data_off). Pass --info for another metadata
file, or --text-base/--rodata-base/--data-base to supply bases explicitly.

Usage:
  python tools/d3-re/dis_stringrefs.py 0x8009000 --count 4000
  python tools/d3-re/dis_stringrefs.py 0x8009000 --info out/windows/kbm/b2/runtime_info.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG

OUT_DIR = Path("out/windows/kbm/b2")
TEXT = OUT_DIR / "runtime_text.bin"
RODATA = OUT_DIR / "runtime_rodata.bin"
DATA = OUT_DIR / "runtime_data.bin"
INFO_NAME = "runtime_info.json"


def as_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected integer, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"{field}: expected integer or numeric string, got {type(value).__name__}")


def load_main_info(info_path: Path) -> dict:
    if not info_path.is_file():
        raise SystemExit(
            f"error: metadata not found: {info_path}. "
            "Point --info at runtime_info.json, or pass --text-base/--rodata-base/--data-base."
        )
    data = json.loads(info_path.read_text(encoding="utf-8"))
    main = data.get("main")
    if not isinstance(main, dict):
        raise SystemExit(f"error: {info_path}: no 'main' record")
    return main


def segment_bases(paths: dict[str, Path], info: Path | None,
                  overrides: dict[str, int | None]) -> tuple[dict[str, tuple[bytes, int]], str]:
    """Return {name: (blob, guest_base)} plus a description of the source."""
    if all(overrides.get(name) is not None for name in paths):
        bases = {name: overrides[name] for name in paths}
        source = "explicit --*-base values"
    else:
        info_path = info or (paths["rodata"].parent / INFO_NAME)
        main = load_main_info(info_path)
        image = as_int(main.get("base"), "main.base")
        offsets = {
            "text": as_int(main.get("text_off", 0), "main.text_off"),
            "rodata": as_int(main.get("ro_off"), "main.ro_off"),
            "data": as_int(main.get("data_off"), "main.data_off"),
        }
        bases = {name: overrides.get(name) or image + offsets[name] for name in paths}
        source = str(info_path)
    for name, path in paths.items():
        if not path.is_file():
            raise SystemExit(f"error: dump not found: {name}: {path}")
    return {name: (path.read_bytes(), bases[name]) for name, path in paths.items()}, source


def cstr(segments, guest: int) -> str | None:
    for name in ("rodata", "data"):
        blob, base = segments[name]
        off = guest - base
        if 0 <= off < len(blob):
            end = blob.find(b"\0", off, off + 160)
            if end > off:
                raw = blob[off:end]
                if all(32 <= c < 127 for c in raw):
                    return raw.decode("ascii")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("start", type=lambda s: int(s, 0), help="guest address of the first instruction")
    ap.add_argument("--count", type=int, default=200, help="instructions to disassemble")
    ap.add_argument("--info", type=Path, default=None, help="runtime_info.json (default: beside the dumps)")
    ap.add_argument("--text", type=Path, default=TEXT)
    ap.add_argument("--rodata", type=Path, default=RODATA)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--text-base", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--rodata-base", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--data-base", type=lambda s: int(s, 0), default=None)
    args = ap.parse_args()
    segments, source = segment_bases(
        {"text": args.text, "rodata": args.rodata, "data": args.data},
        args.info,
        {"text": args.text_base, "rodata": args.rodata_base, "data": args.data_base},
    )
    text_blob, text_base = segments["text"]
    start = args.start
    if not text_base <= start < text_base + len(text_blob):
        raise SystemExit(
            f"error: start 0x{start:08x} outside text 0x{text_base:08x}-0x{text_base + len(text_blob):08x}"
        )
    code = text_blob[start - text_base:start - text_base + args.count * 4]
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    insns = list(md.disasm(code, start))
    pending = None  # (page, insn addr, reg)
    for i, insn in enumerate(insns):
        text = None
        if insn.mnemonic == "adrp" and len(insn.operands) == 2 and insn.operands[0].type == ARM64_OP_REG:
            pending = (insn.operands[1].imm, insn.address, insn.operands[0].reg)
        elif insn.mnemonic == "add" and pending and len(insn.operands) == 3:
            dst, src, imm = insn.operands
            if src.type == ARM64_OP_REG and src.reg == pending[2] and imm.type == ARM64_OP_IMM:
                target = pending[0] + imm.imm
                text = cstr(segments, target)
                if text:
                    consts = []
                    for nxt in insns[i + 1:i + 6]:
                        if nxt.mnemonic == "mov" and len(nxt.operands) == 2 and nxt.operands[1].type == ARM64_OP_IMM:
                            consts.append(f"{nxt.op_str.split(',')[0].strip()}={nxt.operands[1].imm:#x}")
                        if nxt.mnemonic.startswith("bl"):
                            break
                    print(f"0x{insn.address:08x} -> 0x{target:08x} {text!r:<40} {' '.join(consts)}")
                pending = None
    print(f"-- {len(insns)} instructions from 0x{start:08x} (bases from {source})")


if __name__ == "__main__":
    main()
