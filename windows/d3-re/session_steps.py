"""Run a serial step list in one Frida attach and snapshot UI/state after each step.

Each step is an object with optional ``action`` (the same shape accepted by
session_driver: key/click/move/drag/wheel), ``sleep_ms`` and ``label``.  The
output keeps every snapshot so a page's open/close or a multi-key sequence can
be verified without one attach per action.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import frida

import probe_ui_tree
import session_driver
import version

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--steps", required=True, help="JSON list of step objects")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    build = version.assert_installed()
    identity = session_driver._process_identity(args.pid)
    steps = json.loads(args.steps)
    if not isinstance(steps, list):
        raise SystemExit("--steps must be a JSON list")
    session = frida.get_local_device().attach(args.pid)
    snapshots = []
    try:
        script = session.create_script(probe_ui_tree.JS + session_driver.DRIVER_JS)
        script.load()
        for index, step in enumerate(steps):
            label = step.get("label", f"step-{index}")
            action = step.get("action")
            sent = None
            if action is not None:
                prepared = session_driver._prepare([action])
                sent = script.exports_sync.drive([prepared[0]["action"]])
            delay = float(step.get("sleep_ms", 350))
            time.sleep(delay / 1000.0)
            state = script.exports_sync.state()
            ui = script.exports_sync.dump(None, True)
            snapshots.append({"index": index, "label": label, "sent": sent,
                              "state": state, "ui": ui})
    finally:
        session.detach()
    payload = {"build": build, "identity": identity, "steps": snapshots}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    for snap in snapshots:
        texts = []
        for item in snap["ui"].get("items", []):
            text = (item.get("text") or "").strip()
            if text and text not in texts:
                texts.append(text)
        print(f"{snap['label']}: ui_blocked={snap['state']['ui_blocked']} serial={snap['state']['serial']} items={len(snap['ui'].get('items', []))}")
        for text in texts[:12]:
            print("  " + text[:120].replace("\n", " | "))

if __name__ == "__main__":
    main()
