"""Inject one SDL click and capture movement, target action and neutral input.

This verifies transport and command identity. Business results (dialog text,
inventory, opened gizmo or destination world) must be captured separately.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import time
from pathlib import Path

import frida

import probe_interact_flow
import probe_pointer_click
import probe_world_move
import probe_ui_snapshot
from version import assert_installed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--screen", required=True)
    ap.add_argument("--target", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    x,y = (float(v) for v in args.screen.split(","))
    if not (0 <= x < 1280 and 0 <= y < 720 and 1 <= args.seconds <= 40):
        ap.error("invalid pixel or duration")
    build = assert_installed()
    session = frida.get_local_device().attach(args.pid)
    hook_errors = []
    def on_message(message, _data):
        if message.get("type") == "error":
            hook_errors.append(message)
    try:
        movement = session.create_script(probe_world_move.JS)
        movement.on("message",on_message)
        movement.load()
        flow = session.create_script(probe_interact_flow.JS)
        flow.on("message",on_message)
        flow.load()
        pointer = session.create_script(probe_pointer_click.JS)
        pointer.on("message",on_message)
        pointer.load()
        ui = session.create_script(probe_ui_snapshot.JS)
        ui.on("message",on_message)
        ui.load()
        ui_names = probe_ui_snapshot.names_for("consoleconversation|consoleinventoryring_main.*(vendorpanel|merchantlist)")
        ui_states = []
        time.sleep(0.25)
        click = pointer.exports_sync.click(x,y,1280,720)
        start = time.monotonic()
        last = None
        while time.monotonic()-start < args.seconds:
            state = ui.exports_sync.snapshot(ui_names,False)
            state["objects"] = [o for o in state["objects"] if "console" in o["name"]]
            signature = json.dumps(state["objects"],sort_keys=True)
            if signature != last:
                ui_states.append({"seconds":time.monotonic()-start,**state})
                last = signature
            time.sleep(0.15)
        observed = flow.exports_sync.stop()
        moved = movement.exports_sync.stop()
    finally:
        session.detach()
    actions = [c for c in observed["calls"] if c["name"] == "action"]
    records = [struct.unpack_from("<12I",bytes.fromhex(c["record"])) for c in actions]
    downstream = [c for c in observed["calls"] if c["name"] in ("prepare","submit")]
    counts = observed["counts"]
    samples = moved["samples"]
    summary = {"target":hex(args.target),"action_count":len(actions),
        "command_targets":[hex(r[6]) for r in records],
        "powers":[r[2] for r in records],
        "all_complete":all(c.get("complete") for c in actions),
        "all_accepted":all(c.get("ret")==1 for c in actions),
        "neutral_npad":bool(samples) and all(s["axis"]==[0,0] and s["buttons"]=="0" for s in samples),
        "neutral_engine":bool(samples) and all(s["engine"]==[0,0] and s["nativeBits"]==0 for s in samples),
        "distance":math.dist(samples[0]["pos"],samples[-1]["pos"]) if samples else None,
        "exact_counts":all(counts.get(n,0)==1 for n in ("action","prepare","submit")),
        "downstream_target":len(downstream)==2 and all(
            c.get("complete") and c.get("ret")==1 and
            struct.unpack_from("<2I",bytes.fromhex(c["path"]))==(1,args.target)
            for c in downstream),
        "errors":observed["errors"]+moved["errors"]+hook_errors}
    summary["command_pass"] = bool(click["down"] and click["up"] and len(actions)==1 and
        records[0][5]==1 and records[0][6]==args.target and summary["all_complete"] and
        summary["all_accepted"] and summary["neutral_npad"] and summary["neutral_engine"] and
        summary["exact_counts"] and summary["downstream_target"] and
        not summary["errors"])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps({"build":build,"pid":args.pid,"click":click,
        "summary":summary,"ui":ui_states,"flow":observed,"movement":moved},indent=2),"utf-8")
    print(json.dumps(summary,indent=2))
    if not summary["command_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
