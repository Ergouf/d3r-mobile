"""Click a unique visible UI text through SDL and capture both live UI trees."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import frida

import probe_pointer_click
import probe_runtime_state
import probe_ui_snapshot
import probe_ui_tree
from verify_script_interaction import identity, utc
from version import GAME_DIR, assert_installed


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = {"build": assert_installed(), **identity(args.pid), "started_at": utc(),
              "input_transport": "SDL event injection"}
    log = GAME_DIR / "01001B300B9BE000.log"
    offset = log.stat().st_size
    session = frida.get_local_device().attach(args.pid)
    scripts = []
    errors = []

    def load(source):
        script = session.create_script(source)
        script.on("message", lambda m, d: errors.append(m) if m.get("type") == "error" else None)
        script.load()
        scripts.append(script)
        return script.exports_sync

    try:
        tree = load(probe_ui_tree.JS)
        pointer = load(probe_pointer_click.JS)
        runtime = load(probe_runtime_state.JS)
        report["before"] = {"at": utc(), **tree.dump("", True)}
        report["runtime_before"] = runtime.read()
        matches = [v for v in report["before"]["items"] if v.get("text") == args.text]
        if len(matches) != 1:
            raise RuntimeError(f"expected unique visible label, found {len(matches)}")
        target = matches[0]
        report["target"] = target
        names = dict(probe_ui_snapshot.names_for("conversation|questlore|dialog|talk"))
        by_key = {v["key"]: v for v in report["before"]["items"]}
        chain, current = [], target
        while current and len(chain) < 64:
            chain.append({"key": current["key"], "obj": current["obj"],
                          "known_path": names.get(current["key"])})
            current = by_key.get(current["parentKey"])
        report["target_ancestry"] = chain
        r = target["rect2"]
        pixel = [(r[0] + r[2]) / 2 + 160, (r[1] + r[3]) / 2]
        if not (0 <= pixel[0] < 1280 and 0 <= pixel[1] < 720):
            raise RuntimeError("label midpoint outside engine viewport")
        report["clicked_at"] = utc()
        report["click"] = pointer.click(*pixel, 1280, 720)
        if not report["click"]["down"] or not report["click"]["up"]:
            raise RuntimeError("SDL down/up was not queued")
        time.sleep(0.8)
        report["after"] = {"at": utc(), **tree.dump("", True)}
        report["runtime_after"] = runtime.read()
    except Exception as exc:
        report["failure"] = str(exc)
    finally:
        session.detach()
    report["finished_at"] = utc()
    report["errors"] = errors
    if errors:
        report.setdefault("failure", "UI collection reported asynchronous errors")
    with log.open("rb") as fh:
        fh.seek(offset)
        report["log_delta"] = fh.read().decode("utf-8", errors="replace")
    try:
        report["process_identity_unchanged"] = identity(args.pid)["process_start_ticks"] == report["process_start_ticks"]
    except Exception:
        report["process_identity_unchanged"] = False
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    for when in ("before", "after"):
        print(when, [v["text"] for v in report.get(when, {}).get("items", []) if v.get("text")])
    print(report.get("failure", report.get("log_delta", "")))
    return 1 if report.get("failure") or not report["process_identity_unchanged"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
