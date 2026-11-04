#!/usr/bin/env python3
"""Match live UI registry keys against hashes of strings in the runtime rodata.

The registry key (also object+0x30) is a 64-bit name hash. This tries the hash
functions a Blizzard UI/engine may use and reports how many registry keys each
one explains.

Usage:
  python tools/d3-re/match_ui_hashes.py out/windows/kbm/touch/ui_keys_intro.json
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

RODATA = Path("out/windows/kbm/b2/runtime_rodata.bin")
MASK64 = (1 << 64) - 1


def fnv1a64(s: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in s:
        h ^= c
        h = (h * 0x100000001B3) & MASK64
    return h


def fnv164(s: bytes) -> int:
    h = 0xCBF29CE484222325
    for c in s:
        h = (h * 0x100000001B3) & MASK64
        h ^= c
    return h


def djb2_64(s: bytes) -> int:
    h = 5381
    for c in s:
        h = (h * 33 + c) & MASK64
    return h


def djb2a_64(s: bytes) -> int:
    h = 5381
    for c in s:
        h = ((h * 33) ^ c) & MASK64
    return h


def sdbm_64(s: bytes) -> int:
    h = 0
    for c in s:
        h = (c + (h << 6) + (h << 16) - h) & MASK64
    return h


def crc64_ecma(s: bytes) -> int:
    poly = 0x42F0E1EBA9EA3693
    crc = 0
    for c in s:
        crc ^= c << 56
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & MASK64 if crc & (1 << 63) else (crc << 1) & MASK64
    return crc


def murmur64a(s: bytes, seed: int = 0) -> int:
    m = 0xC6A4A7935BD1E995
    r = 47
    h = (seed ^ (len(s) * m)) & MASK64
    n = len(s) // 8
    for i in range(n):
        k = struct.unpack_from("<Q", s, i * 8)[0]
        k = (k * m) & MASK64
        k ^= k >> r
        k = (k * m) & MASK64
        h ^= k
        h = (h * m) & MASK64
    tail = s[n * 8:]
    for i, c in enumerate(tail):
        h ^= c << (8 * i)
    if tail:
        h = (h * m) & MASK64
    h ^= h >> r
    h = (h * m) & MASK64
    h ^= h >> r
    return h


HASHES = {
    "fnv1a64": fnv1a64,
    "fnv164": fnv164,
    "djb2_64": djb2_64,
    "djb2a_64": djb2a_64,
    "sdbm_64": sdbm_64,
    "crc64_ecma": crc64_ecma,
    "murmur64a": murmur64a,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("keys_json", type=Path)
    ap.add_argument("--rodata", type=Path, default=RODATA)
    ap.add_argument("--min", type=int, default=2)
    ap.add_argument("--max", type=int, default=160)
    args = ap.parse_args()

    data = args.rodata.read_bytes()
    strings = set()
    for m in re.finditer(rb"[ -~]{%d,%d}" % (args.min, args.max), data):
        s = m.group()
        if b"\x00" in s:
            continue
        strings.add(s)
        lower = s.lower()
        if lower != s:
            strings.add(lower)
        upper = s.upper()
        if upper != s:
            strings.add(upper)

    raw = json.loads(args.keys_json.read_text(encoding="utf-8"))
    keys = {int(k) & MASK64 for k in raw["keys"]}
    print(f"strings {len(strings)}, keys {len(keys)}")
    for name, fn in HASHES.items():
        table = {}
        for s in strings:
            table.setdefault(fn(s), s)
        hits = keys & table.keys()
        print(f"{name:12s} hits {len(hits):5d} / {len(keys)}")
        for k in list(hits)[:5]:
            print(f"   {k:016x} <- {table[k][:80]!r}")


if __name__ == "__main__":
    main()
