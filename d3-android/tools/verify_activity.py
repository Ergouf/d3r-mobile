#!/usr/bin/env python3
"""D3HOST recovery on-device evidence runner.

Drives ONE non-destructive diagnostic session against the fixed recovery
package and stores every command, exit code, stdout/stderr and timing in a
brand-new --output-dir. Runtime diagnostic evidence is captured both before and
after the run so a damage check is possible.

It touches the device: am force-stop and am start for the recovery package
ONLY, and (with --tap-start) one input tap on its Chinese start button. It
never installs, clears app data, runs logcat -c, builds/packages anything, or
touches com.d3mobile.host (which is only read, to prove it is unchanged).

Exit code 0 means the capture completed; it does NOT imply the guest or game
ran. Requires only the Python standard library.

Run with:  python -I tools/verify_activity.py --adb <abs adb> --output-dir <new dir> \
    --expected-apk-sha256 <64-hex> [--tap-start]
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid

DEVICE = "R52T90127WT"
PKG = "com.d3mobile.host.recovery"
COMPONENT = PKG + "/com.d3mobile.host.MainActivity"
ORIG_PKG = "com.d3mobile.host"
RUNTIME = "/data/user/0/" + PKG + "/files/runtime"
PRIVATE_ROOT = "/data/user/0/" + PKG
MARKERS = ("no-handler", "pause", "selftest-crash", "trace")
SDCARD_D3 = "/sdcard/D3"          # unrelated location; NOT the compile data root
BUTTON_TEXT = "启动兼容层"
# Explicit logcat filters for the normal slice; the per-pid log stays unfiltered.
LOG_TAGS = "D3Host:D D3Recovery:D libc:D DEBUG:D AndroidRuntime:D *:S"
CRASH_NAME_RE = re.compile(r"crash|tombstone|trace|state|maps|\.log$|\.txt$", re.I)
SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def decodeout(out):
    return out.decode("utf-8", errors="replace") if isinstance(out, bytes) else (out or "")


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80]


class Harness:
    """Runs adb commands and records each one into the output dir."""

    def __init__(self, adb, outdir):
        self.adb = adb
        self.outdir = outdir
        self.steps_dir = outdir / "steps"
        self.steps_dir.mkdir()
        self.steps = []
        self.n = 0
        self.failed = False

    def _record(self, name, argv, rc, t0, dur, out, err, required, note):
        self.n += 1
        stem = "%03d_%s" % (self.n, safe(name))
        out_path = self.steps_dir / (stem + ".out")
        err_path = self.steps_dir / (stem + ".err")
        if isinstance(out, bytes):
            out_path.write_bytes(out)
        else:
            out_path.write_text(out or "", encoding="utf-8", errors="replace")
        err_bytes = err if isinstance(err, bytes) else (err or "").encode("utf-8", "replace")
        err_path.write_bytes(err_bytes)
        ok = rc == 0
        if not ok and required:
            self.failed = True
        self.steps.append({
            "n": self.n, "name": name, "argv": argv, "rc": rc, "ok": ok,
            "required": required, "note": note, "started": t0, "duration_s": round(dur, 3),
            "out": str(out_path.relative_to(self.outdir)),
            "err": str(err_path.relative_to(self.outdir)),
            "out_sha256": sha256_bytes(out if isinstance(out, bytes) else (out or "").encode()),
        })
        status = "ok" if ok else ("FAIL" if required else "fail(optional)")
        print("[%s] rc=%s %s" % (status, rc, name))
        return rc, out, err

    def _run(self, name, argv, timeout, required):
        t0, start = now_iso(), time.monotonic()
        note = ""
        try:
            p = subprocess.run(argv, capture_output=True, timeout=timeout)
            rc, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            rc = "timeout"
            out = e.stdout or b""
            err = (e.stderr or b"") + b"\n[runner: subprocess timed out after %ss]" % str(timeout).encode()
            note = "timeout"
        except OSError as e:
            rc, out, err = "oserror", b"", ("[runner: %s]" % e).encode()
            note = "oserror"
        return self._record(name, argv, rc, t0, time.monotonic() - start, out, err, required, note)

    def shell(self, name, cmd, *, timeout=60, required=True):
        return self._run(name, [self.adb, "-s", DEVICE, "shell", cmd], timeout, required)

    def exec_out(self, name, cmd, *, timeout=60, required=True):
        return self._run(name, [self.adb, "-s", DEVICE, "exec-out", cmd], timeout, required)

    def write_summary(self, **extra):
        (self.outdir / "steps.json").write_text(json.dumps(self.steps, indent=2), encoding="utf-8")
        summary = {
            "device": DEVICE, "package": PKG, "component": COMPONENT,
            "original_package": ORIG_PKG, "runtime_root": RUNTIME,
            "generated": now_iso(), "any_required_failed": self.failed,
            "step_count": len(self.steps),
            "exit_note": "exit 0 = capture completed only; it does NOT imply the guest ran",
        }
        summary.update(extra)
        (self.outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def present_markers(h):
    """Markers under the compile data root, or None if the listing failed.

    A failed run-as/ls is NOT treated as 'no markers': None forces a refusal.
    """
    rc, out, _ = h.shell("list_runtime_root", "run-as %s ls -1 %s" % (PKG, RUNTIME),
                         required=False)
    if rc != 0:
        return None
    listing = set(decodeout(out).split())
    return [m for m in MARKERS if m in listing]


def capture_runtime_diag(h, tag):
    """Capture ONLY diagnostic logs + crash files, never game data.

    tar of <runtime>/logs, plus any crash-named files directly under
    <private>/files and <private>/cache (one level, name-filtered).
    Returns {remote_path -> sha256}.
    """
    ev = h.outdir / ("%s_evidence" % tag)
    ev.mkdir(parents=True, exist_ok=True)
    manifest = {}
    h.shell("%s_ls_runtime" % tag, "run-as %s ls -la %s %s/logs" % (PKG, RUNTIME, RUNTIME),
            required=False)
    rc, data, _ = h.exec_out("%s_logs_tar" % tag,
                             "run-as %s tar -c -f - -C %s/logs ." % (PKG, RUNTIME),
                             timeout=120, required=False)
    if rc == 0 and data:
        (ev / "logs.tar").write_bytes(data)
        manifest["<runtime>/logs.tar"] = sha256_bytes(data)
    for sub in ("files", "cache"):
        rc, listing, _ = h.shell("%s_ls_%s" % (tag, sub),
                                 "run-as %s ls -1 %s/%s" % (PKG, PRIVATE_ROOT, sub),
                                 required=False)
        if rc != 0:
            continue
        for name in decodeout(listing).split():
            if not CRASH_NAME_RE.search(name):
                continue
            remote = "%s/%s/%s" % (PRIVATE_ROOT, sub, name)
            r, d, _ = h.exec_out("%s_cat_%s" % (tag, sub),
                                 "run-as %s cat %s" % (PKG, remote), required=False)
            if r == 0:
                (ev / safe("%s_%s" % (sub, name))).write_bytes(d)
                manifest[remote] = sha256_bytes(d)
    return manifest


def capture_sdcard_d3(h, tag):
    """List /sdcard/D3 only; no find, no cat. It is NOT the compile data root."""
    h.shell("%s_sdcard_d3_ls" % tag, "ls -la %s" % SDCARD_D3, required=False)
    h.shell("%s_sdcard_d3_logs_ls" % tag, "ls -la %s/logs" % SDCARD_D3, required=False)


def prove_original_untouched(h, filename):
    """Read the original package path and its on-device sha256 (proof only)."""
    rc, out, _ = h.shell("orig_pm_path", "pm path %s" % ORIG_PKG, required=False)
    paths = [l.split(":", 1)[1] for l in decodeout(out).splitlines() if l.startswith("package:")]
    record = {"package": ORIG_PKG, "apk_paths": paths, "sha256": {}}
    for p in paths:
        r, summ, _ = h.shell("orig_sha256", "sha256sum %s" % p, required=False)
        record["sha256"][p] = decodeout(summ).split()[0] if decodeout(summ).strip() else ""
    (h.outdir / filename).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def prove_installed_recovery(h, expected_sha256, filename="recovery_installed.sha256.json"):
    """Read the recovery package path + on-device sha256 (separate proof).

    The caller passes the sha256 of the build it just installed (--expected-apk-
    sha256); the installed APK is matched against THAT, never a hardcoded value,
    so an unknown package can never be accepted as the new build.
    """
    rc, out, _ = h.shell("recovery_pm_path", "pm path %s" % PKG, required=False)
    paths = [l.split(":", 1)[1] for l in decodeout(out).splitlines() if l.startswith("package:")]
    shas = {}
    for p in paths:
        r, summ, _ = h.shell("recovery_sha256", "sha256sum %s" % p, required=False)
        shas[p] = decodeout(summ).split()[0] if decodeout(summ).strip() else ""
    record = {
        "package": PKG, "apk_paths": paths, "sha256": shas,
        "expected_sha256": expected_sha256.lower(),
        "matches_expected": expected_sha256.lower() in [s.lower() for s in shas.values()],
    }
    (h.outdir / filename).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def find_start_button(xml, package, label):
    """Center + bounds of an enabled node with exact text and package, else None."""
    for m in re.finditer(r"<node\b[^>]*>", xml):
        tag = m.group(0)
        t = re.search(r'text="([^"]*)"', tag)
        p = re.search(r'package="([^"]*)"', tag)
        e = re.search(r'enabled="([^"]*)"', tag)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if (t and t.group(1) == label and p and p.group(1) == package
                and e and e.group(1) == "true" and b):
            x1, y1, x2, y2 = (int(g) for g in b.groups())
            return (x1 + x2) // 2, (y1 + y2) // 2, (x1, y1, x2, y2)
    return None


def tap_start(h):
    """Dump UI and tap the enabled start button. True only on a real rc=0 tap."""
    dump = "/sdcard/d3_verify_%s.xml" % uuid.uuid4().hex[:12]
    rc, _, _ = h.shell("uiautomator_dump", "uiautomator dump %s" % dump,
                       timeout=45, required=False)
    rc2, xml, _ = h.exec_out("uiautomator_read", "cat %s" % dump, required=False)
    if rc != 0 or rc2 != 0:
        print("[FAIL] uiautomator dump/read failed")
        return False
    doc = decodeout(xml)
    found = find_start_button(doc, PKG, BUTTON_TEXT)
    if not found:
        (h.outdir / "ui_dump.xml").write_text(doc, encoding="utf-8")
        print("[FAIL] enabled %r button for %s not found in UI dump" % (BUTTON_TEXT, PKG))
        return False
    cx, cy, bounds = found
    rc3, _, _ = h.shell("input_tap_start", "input tap %d %d" % (cx, cy), required=True)
    (h.outdir / "tap_start.json").write_text(json.dumps(
        {"label": BUTTON_TEXT, "package": PKG, "center": [cx, cy], "bounds": bounds,
         "tap_rc": rc3}, indent=2), encoding="utf-8")
    return rc3 == 0


def get_pid(h):
    rc, out, _ = h.shell("pidof", "pidof %s" % PKG, required=False)
    return decodeout(out).strip().split()[0] if decodeout(out).strip() else None


def sample_once(h, i, pid):
    """Per-second process/thread sampling (screenshots are separate, two at most).

    ps fields are the ones the device actually supports (PID,TID,STAT,NAME,TIME,
    CPU); `CP` does not exist and made ps print its help. Per-thread
    /proc/<pid>/task/*/stat is also read raw so a busy-spin can be shown later.
    """
    if not (pid and pid.isdigit()):
        return
    h.shell("iter%02d_ps_T" % i,
            "ps -T -p %s -o PID,TID,STAT,NAME,TIME,CPU" % pid, required=False)
    h.exec_out("iter%02d_proc_stat" % i, "run-as %s cat /proc/%s/stat" % (PKG, pid), required=False)
    h.exec_out("iter%02d_task_stat" % i,
               "run-as %s sh -c 'for t in /proc/%s/task/*; do cat $t/stat; done'" % (PKG, pid),
               required=False)
    h.exec_out("iter%02d_threads" % i, "run-as %s ls -1 /proc/%s/task" % (PKG, pid), required=False)
    h.exec_out("iter%02d_maps" % i, "run-as %s cat /proc/%s/maps" % (PKG, pid), required=False)


def collect_logcat(h, since, pid):
    if pid:
        h.shell("logcat_pid", "logcat -d -v threadtime -T '%s' --pid=%s" % (since, pid),
                timeout=60, required=False)
    h.shell("logcat_slice", "logcat -d -v threadtime -T '%s' %s" % (since, LOG_TAGS),
            timeout=60, required=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adb", required=True, help="absolute path to adb")
    ap.add_argument("--output-dir", required=True,
                    help="brand-new empty dir; refused if it exists non-empty")
    ap.add_argument("--expected-apk-sha256", required=True,
                    help="sha256 (64 hex) of the recovery APK build just installed; "
                         "the on-device package must match it")
    ap.add_argument("--duration-seconds", type=int, default=15)
    ap.add_argument("--tap-start", action="store_true",
                    help="dump UI and tap the enabled '启动兼容层' button (failure is fatal)")
    ap.add_argument("--stop-after", action="store_true",
                    help="explicitly force-stop the recovery app after the run")
    args = ap.parse_args(argv)

    if os.name == "nt" and not os.path.isabs(args.adb):
        ap.error("--adb must be an absolute path")
    if not SHA256_HEX_RE.match(args.expected_apk_sha256):
        ap.error("--expected-apk-sha256 must be 64 hex characters")

    outdir = pathlib.Path(args.output_dir)
    if outdir.exists():
        if any(outdir.iterdir()):
            ap.error("--output-dir already exists and is not empty: %s" % outdir)
    else:
        outdir.mkdir(parents=True)

    h = Harness(args.adb, outdir)
    (outdir / "runner_command.txt").write_text(" ".join(sys.argv) + "\n", encoding="utf-8")
    extra = {"refused": False, "markers_present": None, "pid_last_seen": None, "app_alive": False}

    # 1. Installed recovery proof + original-package proof (both read-only).
    try:
        installed = prove_installed_recovery(h, args.expected_apk_sha256)
        pre_orig = prove_original_untouched(h, "original_package.before.sha256.json")
    except OSError as e:
        h.failed = True
        print("[FAIL] adb not runnable: %s" % e)
        h.write_summary(**extra)
        return 2
    extra["recovery_installed"] = installed
    if not installed["matches_expected"]:
        msg = ("REFUSED: installed %s does not match --expected-apk-sha256 %s; "
               "refusing to treat an unknown package as the new build. Installed: %s"
               % (PKG, args.expected_apk_sha256.lower(),
                  installed["sha256"] or "(none)"))
        (outdir / "REFUSED").write_text(msg + "\n", encoding="utf-8")
        extra["refused"] = True
        print("[REFUSED] " + msg)
        h.write_summary(**extra)
        return 3

    # 2. Pre-run evidence (diagnostic only), before any modification.
    extra["pre_evidence"] = capture_runtime_diag(h, "pre")
    capture_sdcard_d3(h, "pre")

    # 3. Refuse on markers, or when the listing itself could not be read.
    present = present_markers(h)
    extra["markers_present"] = present
    if present is None:
        (outdir / "REFUSED").write_text(
            "REFUSED: could not list %s (run-as/ls failed); cannot rule out "
            "diagnostic markers.\n" % RUNTIME, encoding="utf-8")
        extra["refused"] = True
        print("[REFUSED] runtime root not listable; refusing normal acceptance")
        h.write_summary(**extra)
        return 3
    if present:
        msg = ("REFUSED: diagnostic markers present under %s: %s\n"
               "These switch crash/pause/trace paths on purpose and are NOT "
               "deleted here. Remove them deliberately before normal acceptance."
               % (RUNTIME, ", ".join(present)))
        (outdir / "REFUSED").write_text(msg + "\n", encoding="utf-8")
        extra["refused"] = True
        print("[REFUSED] " + msg)
        h.write_summary(**extra)
        return 3

    # 4. Cold start the recovery app only (real Activity, no autostart extra).
    h.shell("force_stop_recovery", "am force-stop %s" % PKG, required=False)
    rc, tsout, _ = h.shell("device_time", "date '+%m-%d %H:%M:%S.000'", required=True)
    ts = decodeout(tsout).strip()
    since = ts.splitlines()[0] if ts else ""
    h.shell("am_start", "am start -n %s" % COMPONENT, required=True)

    # 5. Optional: one screenshot before the tap, tap, one screenshot after.
    if args.tap_start:
        time.sleep(2)
        h.exec_out("screenshot_before_click", "screencap -p", required=False)
        if not tap_start(h):
            h.failed = True
        time.sleep(2)
        h.exec_out("screenshot_after_window", "screencap -p", required=False)

    # 6. Sample the live process for --duration-seconds.
    for i in range(1, args.duration_seconds + 1):
        time.sleep(1)
        cur = get_pid(h)
        extra["app_alive"] = cur is not None
        if cur:
            extra["pid_last_seen"] = cur
            sample_once(h, i, cur)
        if i % 5 == 0:
            collect_logcat(h, since, cur)
    final_pid = get_pid(h)
    extra["app_alive"] = final_pid is not None
    if final_pid:
        extra["pid_last_seen"] = final_pid
    collect_logcat(h, since, final_pid)

    # 7. Optional explicit stop (default: leave it running).
    if args.stop_after:
        h.shell("stop_after", "am force-stop %s" % PKG, required=False)

    # 8. Post-run evidence + original package proof (after), for comparison.
    extra["post_evidence"] = capture_runtime_diag(h, "post")
    capture_sdcard_d3(h, "post")
    post_orig = prove_original_untouched(h, "original_package.after.sha256.json")
    extra["original_unchanged"] = pre_orig["sha256"] == post_orig["sha256"]

    h.write_summary(**extra)
    print("done: %d steps, app_alive=%s, any_required_failed=%s"
          % (len(h.steps), extra["app_alive"], h.failed))
    return 1 if h.failed else 0


if __name__ == "__main__":
    sys.exit(main())
