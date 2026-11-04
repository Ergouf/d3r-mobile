"""Walk the player to a world position using the game's own camera projection.

Each step: read the player position, aim at a point at most `--step` units along
the line to the target, **check that the projected pixel would not pick an
entity's native collision cylinder** (a prop in front of the camera turns the click into an operate/attack
goal instead of a walk), project through the engine camera
(probe_guest_call --project), inject one SDL left click there, and stop when the
player is within `--reach`, when three steps make no progress, when the place
changes, or after `--max` steps.

Usage:
  python tools/d3-re/walk_to.py --pid 1234 --context 0x... --to 2877,2882
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = sys.executable
SCENE = ROOT / "out/windows/kbm/walk_to-scene.json"
PROJ = ROOT / "out/windows/kbm/walk_to-project.json"
PICK = ROOT / "out/windows/kbm/walk_to-pick.json"


def run(args: list[str], out: Path | None = None) -> dict | None:
    """Run one probe; drop its stale output first and return the parsed JSON."""
    if out is not None and out.exists():
        out.unlink()
    cmd = [PY, str(HERE / args[0])] + args[1:]
    # Frida's Windows helper can inherit a pipe handle after the probe exits.
    # A file avoids waiting for EOF from that helper in communicate().
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=35)
        log.seek(0)
        output = log.read()
    if out is not None:
        out.with_suffix(".log").write_text(output, "utf-8")
    if r.returncode != 0 or out is None or not out.exists():
        return None
    try:
        return json.loads(out.read_text("utf-8"))
    except Exception:
        return None


def player(pid: int, context: str):
    data = run(["probe_click_interact.py", "--pid", str(pid), "--context", context,
                "--radius", "1", "--out", str(SCENE)], SCENE)
    r = (data or {}).get("result") or {}
    if not r.get("ok"):
        return None
    return r["pos"], int(r["actor"], 16), r["place"]


def project(pid: int, context: str, actor: int, offset: list[float]):
    data = run(["probe_guest_call.py", "--pid", str(pid), "--context", context,
                "--actor", hex(actor), "--project",
                "--offset=%.3f,%.3f,%.3f" % tuple(offset), "--out", str(PROJ)], PROJ)
    r = (data or {}).get("result") or {}
    if not r.get("ok"):
        return None
    pix = r.get("pixel")
    if not isinstance(pix, list) or len(pix) < 2:
        return None
    return float(pix[0]), float(pix[1]), r.get("viewport") or [0, 0, 1280, 720]


def entity_at(pid: int, context: str, x: float, y: float):
    """Reject native collision hits and the projected assist target gate."""
    data = run(["probe_click_interact.py", "--pid", str(pid), "--context", context,
                "--click", "%d,%d" % (round(x), round(y)), "--radius", "200",
                "--out", str(PICK)], PICK)
    r = (data or {}).get("result") or {}
    if not r.get("ok"):
        raise RuntimeError("entity pick probe failed; refusing an unchecked click")
    if "cylinderHits" not in r or "assistCandidates" not in r:
        raise RuntimeError("pick probe lacks collision/assist results; refusing an unchecked click")
    hits = r["cylinderHits"]
    if hits:
        hit = dict(hits[0])
        hit["nativeCylinder"] = True
        hit["screenDistance"] = -1.0  # native cylinder intersection, irrespective of label distance
        return hit
    if r["assistCandidates"]:
        return r["assistCandidates"][0]
    cands = r.get("candidates") or []
    if not cands:
        return None
    c = cands[0]
    return c if c.get("screenDistance", 1e9) <= 14.0 else None


def click(pid: int, x: float, y: float, viewport: list[int], out: Path | None = None) -> bool:
    w = int(viewport[2]) or 1280
    h = int(viewport[3]) or 720
    if not (0 <= x < w and 0 <= y < h):
        return False
    cmd = [PY, str(HERE / "probe_pointer_click.py"), "--pid", str(pid),
           "--x", "%.1f" % x, "--y", "%.1f" % y,
           "--width", str(w), "--height", str(h)]
    if out is not None:
        out.unlink(missing_ok=True)
        cmd += ["--out", str(out)]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=35)
        log.seek(0)
        output = log.read()
    if out is not None:
        out.with_suffix(".log").write_text(output, "utf-8")
    return r.returncode == 0 and '"down": 1' in output and '"up": 1' in output


def main() -> None:
    global SCENE, PROJ, PICK
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--context", default="0x150030E60")
    ap.add_argument("--to", required=True, help="world x,y (z is ignored)")
    ap.add_argument("--step", type=float, default=28.0)
    ap.add_argument("--reach", type=float, default=6.0)
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--wait", type=float, default=2.5)
    ap.add_argument("--out-dir", type=Path, help="keep each step/attempt's raw probe JSON")
    args = ap.parse_args()
    target = [float(v) for v in args.to.split(",")][:2]
    if len(target) != 2 or not all(math.isfinite(v) for v in target):
        ap.error("--to requires two finite world coordinates")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    print("target (%.1f,%.1f) step %.0f reach %.0f max %d" % (target[0], target[1],
                                                              args.step, args.reach, args.max))
    last = None
    stalled = 0
    place0 = None
    for i in range(args.max):
        if args.out_dir:
            SCENE = args.out_dir / f"step-{i:02d}-scene.json"
        cur = player(args.pid, args.context)
        if cur is None:
            print("step %d: no player state (stale output or probe failure)" % i)
            return
        pos, actor, place = cur
        place0 = place0 if place0 is not None else place
        if place != place0:
            print("step %d: place changed %d -> %d, stop" % (i, place0, place))
            return
        dx, dy = target[0] - pos[0], target[1] - pos[1]
        dist = math.hypot(dx, dy)
        if last is not None and abs(last - dist) < 0.5:
            stalled += 1
        else:
            stalled = 0
        last = dist
        print("step %d: at (%.1f,%.1f) dist %.1f (stalled %d)" % (i, pos[0], pos[1], dist, stalled))
        if dist <= args.reach:
            print("reached")
            return
        if stalled >= 3:
            print("no progress for 3 steps, stop")
            return
        k = min(args.step, dist) / dist
        base = [dx * k, dy * k, 0.0]
        pix = None
        viewport = [0, 0, 1280, 720]
        for attempt in range(3):
            if args.out_dir:
                PROJ = args.out_dir / f"step-{i:02d}-attempt-{attempt}-project.json"
                PICK = args.out_dir / f"step-{i:02d}-attempt-{attempt}-pick.json"
            # shift the aim sideways when the direct line would click a prop
            off = [base[0], base[1], 0.0]
            if attempt:
                px, py = -dy / dist, dx / dist
                sign = 1.0 if attempt == 1 else -1.0
                off[0] += px * 12.0 * sign
                off[1] += py * 12.0 * sign
            got = project(args.pid, args.context, actor, off)
            if got is None:
                print("  attempt %d: projection failed" % attempt)
                continue
            x, y, viewport = got
            hit = entity_at(args.pid, args.context, x, y)
            if hit is None:
                pix = (x, y)
                print("  aim (%.1f,%.1f) -> pixel (%.1f,%.1f)" % (off[0], off[1], x, y))
                break
            detail = ("native cylinder, depth %.2f" % hit["depth"] if hit.get("nativeCylinder")
                      else "%.1f px" % hit["screenDistance"])
            print("  attempt %d: pixel (%.1f,%.1f) would hit %s (SNO %s, %s)" %
                  (attempt, x, y, hit.get("id"), hit.get("sno"), detail))
        if pix is None:
            print("step %d: no clear aim point, stop" % i)
            return
        receipt = args.out_dir / f"step-{i:02d}-click.json" if args.out_dir else None
        if not click(args.pid, pix[0], pix[1], viewport, receipt):
            print("step %d: click rejected" % i)
            return
        time.sleep(args.wait)
    if args.out_dir:
        SCENE = args.out_dir / "final-scene.json"
    cur = player(args.pid, args.context)
    if cur:
        print("final (%.1f,%.1f)" % (cur[0][0], cur[0][1]))


if __name__ == "__main__":
    main()
