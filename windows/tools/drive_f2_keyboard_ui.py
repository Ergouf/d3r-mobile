"""Drive the SCARLETNX F2 keyboard-bindings page through real SDL key events.

Phase "edit" walks all 22 rows, rebinding each to a distinct key that does not
collide with the defaults, then checks reserved-key and duplicate-key
rejection.  Phase "defaults" opens the page and activates Restore defaults.
The overlay state (page/focus/top/capture/status) is read from the build's own
static symbols; no pixel or focus assumptions are used.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import sys

import frida

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'windows/d3-re'))
import probe_sdl_key  # noqa: E402
from version import assert_installed, js_consts, _symbol_table, EXE  # noqa: E402

OVERLAY_NAMES = ["backend_kbm_key", "backend_kbm_action", "overlay_shown",
                 "shown", "page", "focus", "top", "keyboard_capture", "keyboard_status"]

PAGE_MAIN = 0
PAGE_KEYBOARD = 5
ITEMS = 24  # 22 bindings + Restore defaults + Back
VISIBLE = 12

CUSTOM = ["5", "6", "7", "8", "9", "0", "f3", "f4", "f5", "f6", "f7", "f8",
          "f9", "f10", "home", "end", "insert", "delete", "pageup", "pagedown",
          "minus", "equals"]


def js_source(rvas):
    return js_consts() + chr(10) + "const R =" + json.dumps(rvas) + r""";
const win = base.add(RVA.sdl_window).readPointer();
const winId = new NativeFunction(base.add(RVA.sdl_get_window_id), 'uint', ['pointer'])(win);
const push = new NativeFunction(base.add(RVA.sdl_push_event), 'bool', ['pointer']);
function sendKey(scan, keycode) {
  for (const down of [1, 0]) {
    const e = Memory.alloc(128);
    e.writeByteArray(new Uint8Array(128));
    e.writeU32(down ? 0x300 : 0x301);
    e.add(16).writeU32(winId);
    e.add(24).writeU32(scan);
    e.add(28).writeU32(keycode);
    e.add(32).writeU16(0);
    e.add(36).writeU8(down);
    push(e);
  }
}
const getKey = new NativeFunction(base.add(R.backend_kbm_key), 'pointer', ['int']);
const getAction = new NativeFunction(base.add(R.backend_kbm_action), 'pointer', ['int']);
const shownFn = new NativeFunction(base.add(R.overlay_shown), 'int', []);
rpc.exports = {
  key(name) {
    const scan = KEYMAP[name][0], code = KEYMAP[name][1];
    sendKey(scan, code);
    return name;
  },
  state() {
    const statusPtr = base.add(R.keyboard_status).readPointer();
    return {
      shown: shownFn(),
      page: base.add(R.page).readS32(),
      focus: base.add(R.focus).readS32(),
      top: base.add(R.top).readS32(),
      capture: base.add(R.keyboard_capture).readS32(),
      status: statusPtr.isNull() ? null : statusPtr.readUtf8String(),
      bindings: Array.from({length: 22}, (_, i) => ({
        index: i, action: getAction(i).readUtf8String(), key: getKey(i).readUtf8String()
      }))
    };
  }
};
""".replace("KEYMAP", json.dumps({name: list(pair) for name, pair in probe_sdl_key.KEYS.items()}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--phase", choices=("edit", "defaults"), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = assert_installed()
    symbols = _symbol_table(EXE)
    missing = [name for name in OVERLAY_NAMES if name not in symbols]
    if missing:
        raise SystemExit(f"missing symbols: {missing}")
    rvas = {name: symbols[name] for name in OVERLAY_NAMES}

    session = frida.attach(args.pid)
    steps = []
    failures = []

    def check(name, ok, detail=None):
        steps.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failures.append({"check": name, "detail": detail})

    try:
        script = session.create_script(js_source(rvas))
        script.load()
        export = script.exports_sync

        def key(name, settle=0.18):
            export.key(name)
            time.sleep(settle)

        def state(settle=0.12):
            time.sleep(settle)
            return export.state()

        before = state()
        check("overlay-closed-before", before["shown"] == 0 and before["capture"] == -1, before)

        key("f2", 0.7)
        opened = state()
        check("f2-overlay-shown", opened["shown"] == 1 and opened["page"] == PAGE_MAIN, opened)

        for _ in range(2):
            key("down")
        key("enter", 0.5)
        page_state = state()
        check("keyboard-page", page_state["page"] == PAGE_KEYBOARD and page_state["focus"] == 0
              and page_state["top"] == 0, page_state)

        if args.phase == "edit":
            tops = []
            for index in range(22):
                if index:
                    key("down")
                focused = state()
                check(f"focus-{index}", focused["focus"] == index, focused)
                expected_top = max(0, index - (VISIBLE - 1))
                check(f"scroll-{index}", focused["top"] == expected_top,
                      {"top": focused["top"], "expected": expected_top})
                tops.append(focused["top"])
                key("enter")
                capture = state()
                check(f"capture-{index}", capture["capture"] == index, capture)
                key(CUSTOM[index])
                saved = state()
                check(f"saved-{index}", saved["capture"] == -1 and saved["status"] == "Saved.",
                      {"capture": saved["capture"], "status": saved["status"],
                       "key": saved["bindings"][index]["key"]})
                check(f"saved-key-{index}", saved["bindings"][index]["key"] == expected_name(CUSTOM[index]),
                      saved["bindings"][index])
            final = state()
            check("all-custom-keys", [b["key"] for b in final["bindings"]] ==
                  [expected_name(name) for name in CUSTOM], [b["key"] for b in final["bindings"]])
            check("scrolled-at-end", final["top"] == 21 - (VISIBLE - 1) and tops[-1] == 21 - (VISIBLE - 1), tops)

            # Back to row 0 across the 21-row wrap, then reserved and duplicate rejection.
            for _ in range(21):
                key("up", 0.06)
            time.sleep(0.2)
            zero = state()
            check("focus-back-to-zero", zero["focus"] == 0 and zero["top"] == 0, zero)
            key("enter")
            check("capture-zero", state()["capture"] == 0, state())
            key("i")
            reserved = state()
            check("reserved-rejected", reserved["capture"] == 0 and reserved["status"] is not None
                  and "reserved" in reserved["status"], reserved)
            key("esc")
            cancelled = state()
            check("escape-cancels-capture", cancelled["capture"] == -1
                  and cancelled["status"] == "Cancelled.", cancelled)
            duplicate = None
            for name in ("6",):
                key("enter")
                key(name)
                duplicate = state()
            check("duplicate-rejected", duplicate["capture"] == 0 and duplicate["status"] is not None
                  and "reserved" in duplicate["status"], duplicate)
            key("esc")
            check("capture-cleared", state()["capture"] == -1, state())

            key("esc", 0.25)
            key("esc", 0.25)
            closed = state()
            check("overlay-closed-after", closed["shown"] == 0, closed)
            check("custom-retained", [b["key"] for b in closed["bindings"]] ==
                  [expected_name(name) for name in CUSTOM], [b["key"] for b in closed["bindings"]])
            result = {"phase": "edit", "custom": [expected_name(n) for n in CUSTOM],
                      "tops": tops}
        else:
            for _ in range(22):
                key("down", 0.05)
            focused = state()
            check("defaults-focused", focused["focus"] == 22, focused)
            key("enter", 0.5)
            restored = state()
            check("defaults-restored", [b["key"] for b in restored["bindings"]] == DEFAULT_KEYS,
                  [b["key"] for b in restored["bindings"]])
            key("esc", 0.25)
            key("esc", 0.25)
            closed = state()
            check("overlay-closed-after", closed["shown"] == 0, closed)
            result = {"phase": "defaults"}

        report = {"build": build, "pid": args.pid, "result": result,
                  "checks": len(steps), "failures": failures, "steps": steps}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
        print(json.dumps({"checks": len(steps), "failures": failures[:4],
                          "result": result}, ensure_ascii=True))
        raise SystemExit(1 if failures else 0)
    finally:
        session.detach()


DEFAULT_KEYS = ["1", "2", "3", "4", "Q", "T", "C", "K", "J", "P", "M", "Escape",
                "W", "A", "S", "D", "Up", "Left", "Down", "Right", "Return", "Backspace"]


def expected_name(name: str) -> str:
    known = {
        "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "0": "0",
        "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
        "f9": "F9", "f10": "F10", "home": "Home", "end": "End", "insert": "Insert",
        "delete": "Delete", "pageup": "PageUp", "pagedown": "PageDown",
        "minus": "-", "equals": "=",
    }
    return known[name]


if __name__ == "__main__":
    main()
