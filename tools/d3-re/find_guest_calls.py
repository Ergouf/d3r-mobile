"""Find AArch64 direct BL/B callers of guest functions in runtime_text.bin."""
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", type=lambda s: int(s, 0))
    args = ap.parse_args()
    blob = Path("out/windows/kbm/b2/runtime_text.bin").read_bytes()
    words = struct.unpack_from(f"<{len(blob) // 4}I", blob)
    hits: dict[int, list[tuple[int, str]]] = {t: [] for t in args.targets}
    for i, word in enumerate(words):
        op = word & 0xFC000000
        if op not in (0x94000000, 0x14000000):
            continue
        delta = word & 0x3FFFFFF
        if delta & 0x2000000:
            delta -= 0x4000000
        pc = 0x8005000 + i * 4
        target = pc + delta * 4
        if target in hits:
            hits[target].append((pc, "bl" if op == 0x94000000 else "b"))
    for target, callers in hits.items():
        print(f"{target:#x}: {len(callers)} caller(s)")
        for pc, kind in callers:
            print(f"  {pc:#x} {kind}")


if __name__ == "__main__":
    main()
