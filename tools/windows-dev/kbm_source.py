"""Source text of the split KBM modules, for source-slicing tests."""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "reference/ScarletNX-src/src/nx/runtime"
FILES = ("native_kbm.h", "native_guest.c", "native_labels.c", "native_ui.c", "native_world.c")


def read_runtime() -> str:
    return "\n".join((RUNTIME / name).read_text(encoding="utf-8") for name in FILES)


def function(source: str, name: str) -> str:
    start = re.search(r"^(?:static )?(?:int|void|u64) " + name + r"\([^;{}]*\)\s*\{", source, re.M).start()
    body = source.index("{", start)
    depth = 0
    tokens = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    for token in tokens.finditer(source, body):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return source[start:token.end()] + "\n"
    raise ValueError("unterminated function " + name)
