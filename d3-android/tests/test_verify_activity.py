"""Regression tests for d3-android/tools/verify_activity.py (stdlib unittest).

No device is touched: an embedded mock "adb" is invoked through sys.executable,
so the real tool's argv building, refusal logic and evidence capture all run.

Run: python -I tests/test_verify_activity.py -v
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "verify_activity.py"

# The mock adb. Reads D3_MOCK_CFG (JSON) for scenario responses and appends every
# invocation (the adb arguments) to the file named by D3_MOCK_LOG.
MOCK_ADB = r'''
import json, os, sys
cfg = json.load(open(os.environ["D3_MOCK_CFG"], "r", encoding="utf-8"))
args = sys.argv[1:]
with open(os.environ["D3_MOCK_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\n")
cmd = " ".join(args)
def o(t): sys.stdout.buffer.write(t.encode("utf-8"))
def b(x): sys.stdout.buffer.write(x)
if " tar " in cmd and "run-as" in cmd:
    b(b"\x1f\x8bFAKE-LOGS-TAR\x00\x01"); sys.exit(0)
if "screencap" in cmd:
    b(b"\x89PNG\r\n\x1a\nFAKEPNG"); sys.exit(0)
if "uiautomator dump" in cmd:
    o("UI hierchary dumped\n"); sys.exit(0)
if "cat /sdcard/d3_verify_" in cmd:
    o(cfg.get("window_xml", "")); sys.exit(0)
if cmd.rstrip().endswith("/runtime") and "ls -1" in cmd:
    if cfg.get("ls_fail"): sys.exit(1)
    o("\n".join(cfg.get("markers", [])) + ("\n" if cfg.get("markers") else "")); sys.exit(0)
if "ls -1" in cmd and ("/files" in cmd or "/cache" in cmd):
    o("\n".join(cfg.get("files_entries", [])) + "\n"); sys.exit(0)
if "ls -la" in cmd:
    o("total 0\n"); sys.exit(0)
if "run-as" in cmd and " cat " in cmd:
    o("CRASH-BYTES\n"); sys.exit(0)
if "pm path com.d3mobile.host.recovery" in cmd:
    o("package:%s\n" % cfg["recovery_path"]); sys.exit(0)
if "pm path com.d3mobile.host" in cmd:
    o("package:/data/app/orig/base.apk\n"); sys.exit(0)
if "sha256sum" in cmd:
    if "recovery" in cmd:
        o("%s  %s\n" % (cfg["recovery_sha"], cfg["recovery_path"]))
    else:
        o("1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7  /data/app/orig/base.apk\n")
    sys.exit(0)
if "date " in cmd:
    o("10-16 21:30:00.000\n"); sys.exit(0)
if "pidof" in cmd:
    if cfg.get("pid"): o(cfg["pid"] + "\n")
    sys.exit(0)
if "ps -T" in cmd:
    o("PID TID STAT NAME TIME CPU\n%s %s S d3.recovery 00:00:01 12\n"
      % (cfg.get("pid"), cfg.get("pid"))); sys.exit(0)
if "sh -c" in cmd and "/task/" in cmd:
    o("%s (d3.recovery) S 1 1 0 0 -1 4194560 0 0 0 0 7 0\n" % cfg.get("pid")); sys.exit(0)
if "logcat" in cmd:
    o("10-16 21:30 Log I d3host: nnMain\n"); sys.exit(0)
o("ok\n")
'''


def load_tool():
    spec = importlib.util.spec_from_file_location("verify_activity_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()

OK_BUTTON = ('<hierarchy><node text="启动兼容层" package="%s" enabled="true" '
             'bounds="[40,600][900,680]"/></hierarchy>' % tool.PKG)


class MockHarness(tool.Harness):
    """Harness whose adb is the mock script, run through sys.executable."""

    def __init__(self, adb, outdir, mock_path, cfg_path, log_path):
        super().__init__(adb, outdir)
        self._mock, self._cfg, self._log = mock_path, cfg_path, log_path

    def _run(self, name, argv, timeout, required):
        env = dict(os.environ, D3_MOCK_CFG=str(self._cfg), D3_MOCK_LOG=str(self._log))
        real = [sys.executable, "-I", str(self._mock)] + argv[1:]
        t0, t = tool.now_iso(), time.monotonic()
        try:
            p = subprocess.run(real, capture_output=True, timeout=timeout, env=env)
            rc, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            rc, out, err = "timeout", e.stdout or b"", b"timeout"
        return self._record(name, real, rc, t0, time.monotonic() - t,
                            out, err, required, "")


class VerifyActivityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.mock = self.root / "mock_adb.py"
        self.mock.write_text(MOCK_ADB, encoding="utf-8")
        self.cfg = self.root / "cfg.json"
        self.log = self.root / "adb_calls.log"
        self.log.write_text("", encoding="utf-8")
        # The caller-supplied expected build hash (what --expected-apk-sha256 carries).
        self.expected = "a" * 64

    def write_cfg(self, **over):
        cfg = {
            "recovery_path": "/data/app/~~r==/com.d3mobile.host.recovery/base.apk",
            "recovery_sha": self.expected,
            "window_xml": OK_BUTTON, "markers": [], "files_entries": [], "pid": "32104",
        }
        cfg.update(over)
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")

    def run_tool(self, *extra, outname="out", expected=None):
        outdir = self.root / outname
        orig = tool.Harness
        tool.Harness = lambda adb, od: MockHarness(adb, od, self.mock, self.cfg, self.log)
        self.addCleanup(setattr, tool, "Harness", orig)
        argv = ["--adb", sys.executable, "--output-dir", str(outdir),
                "--expected-apk-sha256", expected or self.expected,
                "--duration-seconds", "2"] + list(extra)
        return tool.main(argv), outdir

    def adb_calls(self):
        return [l for l in self.log.read_text(encoding="utf-8").splitlines() if l]

    def read_summary(self, outdir):
        return json.loads((outdir / "summary.json").read_text(encoding="utf-8"))

    # --- required cases ---------------------------------------------------

    def test_marker_listing_failure_must_refuse(self):
        # run-as/ls failing must NOT be read as "no markers".
        self.write_cfg(ls_fail=True)
        rc, outdir = self.run_tool()
        self.assertEqual(rc, 3)
        self.assertTrue((outdir / "REFUSED").exists())
        self.assertFalse((outdir / "tap_start.json").exists())
        # must not have started the app at all
        self.assertFalse(any("am start" in c for c in self.adb_calls()))

    def test_markers_present_must_refuse_without_deleting(self):
        self.write_cfg(markers=["no-handler", "trace"])
        rc, outdir = self.run_tool()
        self.assertEqual(rc, 3)
        self.assertIn("no-handler", (outdir / "REFUSED").read_text("utf-8"))
        # no rm/unlink/delete command anywhere
        joined = " ".join(self.adb_calls())
        self.assertNotIn(" rm ", joined)
        self.assertNotIn("unlink", joined)

    def test_recovery_hash_mismatch_refuses_before_start(self):
        # Installed package is an unknown build -> refuse BEFORE force-stop/start.
        self.write_cfg(recovery_sha="b" * 64)
        rc, outdir = self.run_tool()
        self.assertEqual(rc, 3)
        self.assertTrue((outdir / "REFUSED").exists())
        self.assertFalse(any("am force-stop" in c for c in self.adb_calls()))
        self.assertFalse(any("am start" in c for c in self.adb_calls()))
        self.assertFalse(self.read_summary(outdir)["recovery_installed"]["matches_expected"])

    def test_expected_sha256_is_required(self):
        self.write_cfg()
        orig = tool.Harness
        tool.Harness = lambda adb, od: MockHarness(adb, od, self.mock, self.cfg, self.log)
        self.addCleanup(setattr, tool, "Harness", orig)
        with self.assertRaises(SystemExit):
            tool.main(["--adb", sys.executable, "--output-dir", str(self.root / "nosh")])

    def test_tap_button_missing_must_fail(self):
        self.write_cfg(window_xml='<hierarchy><node text="其他" package="%s" '
                                 'enabled="true" bounds="[0,0][10,10]"/></hierarchy>' % tool.PKG)
        rc, outdir = self.run_tool("--tap-start")
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.read_summary(outdir)["any_required_failed"])

    def test_tap_button_disabled_must_fail(self):
        xml = ('<hierarchy><node text="启动兼容层" package="%s" enabled="false" '
               'bounds="[40,600][900,680]"/></hierarchy>' % tool.PKG)
        self.write_cfg(window_xml=xml)
        rc, outdir = self.run_tool("--tap-start")
        self.assertNotEqual(rc, 0)
        # disabled button: no input tap must be issued
        self.assertFalse(any("input tap" in c for c in self.adb_calls()))

    @staticmethod
    def _names_original_package(call):
        # The original package as a bare token: com.d3mobile.host NOT followed by
        # a dot. This ignores com.d3mobile.host.recovery and the Activity class
        # com.d3mobile.host.MainActivity, which live in that namespace by design.
        return re.search(re.escape(tool.ORIG_PKG) + r"(?!\.)", call) is not None

    def test_only_fixed_recovery_and_never_clears_logcat(self):
        self.write_cfg()
        rc, outdir = self.run_tool("--tap-start")
        self.assertEqual(rc, 0)
        calls = self.adb_calls()
        for c in calls:
            # destructive app-domain commands never name the original package
            if any(k in c for k in ("force-stop", "am start", "input tap", "run-as ")):
                self.assertFalse(self._names_original_package(c), c)
            # logcat is never cleared
            self.assertNotIn("logcat -c", c)
            self.assertNotIn("logcat --clear", c)
            self.assertNotIn("pm clear", c)
            # ps must not request the unsupported CP field
            self.assertNotIn("NAME,CP", c)
        # original package is only ever read (pm path / sha256sum)
        orig_calls = [c for c in calls if self._names_original_package(c)]
        self.assertTrue(orig_calls)
        self.assertTrue(all(("pm path" in c) or ("sha256sum" in c) for c in orig_calls))
        # the fixed identity is the one actually targeted
        self.assertTrue(any("force-stop %s" % tool.PKG in c for c in calls))
        self.assertTrue(any("am start -n %s" % tool.COMPONENT in c for c in calls))

    def test_ps_uses_supported_fields_not_CP(self):
        # The device rejects `CP` and prints ps help; only CPU/TIME are valid.
        self.write_cfg()
        rc, outdir = self.run_tool()
        self.assertEqual(rc, 0)
        ps_calls = [c for c in self.adb_calls() if "ps -T" in c]
        self.assertTrue(ps_calls)
        for c in ps_calls:
            self.assertIn("PID,TID,STAT,NAME,TIME,CPU", c)
            self.assertNotIn("NAME,CP", c)

    def test_reads_per_thread_task_stat(self):
        self.write_cfg(pid="7201")
        rc, outdir = self.run_tool()
        self.assertEqual(rc, 0)
        task_calls = [c for c in self.adb_calls()
                      if "/proc/7201/task/" in c and "cat $t/stat" in c]
        self.assertTrue(task_calls)

    def test_no_install_params_exist(self):
        for flag in ("--apk", "--install", "--apk-certified-recovery", "--aapt2"):
            with self.subTest(flag=flag):
                p = subprocess.run(
                    [sys.executable, "-I", str(TOOL_PATH), "--adb", sys.executable,
                     "--output-dir", str(self.root / ("x" + flag.strip("-"))),
                     "--expected-apk-sha256", "a" * 64, flag, "v"],
                    capture_output=True)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("unrecognized arguments", p.stderr.decode("utf-8", "replace"))

    def test_clean_capture_summary_does_not_claim_game_success(self):
        self.write_cfg(pid="32104")
        rc, outdir = self.run_tool("--tap-start")
        self.assertEqual(rc, 0)
        summary = self.read_summary(outdir)
        # only asserts capture completed, and reports real process state
        self.assertIn("does NOT imply the guest", summary["exit_note"])
        self.assertTrue(summary["app_alive"])
        self.assertEqual(summary["pid_last_seen"], "32104")
        self.assertFalse(summary["any_required_failed"])
        blob = json.dumps(summary).lower()
        for claim in ("game_success", "game_ran", "success"):
            self.assertNotIn(claim, blob)
        # before/after original-package proofs are recorded; matching hashes are
        # the normal "unchanged" result (the mock returns the same value twice).
        self.assertEqual(
            json.loads((outdir / "original_package.before.sha256.json").read_text("utf-8"))["sha256"],
            json.loads((outdir / "original_package.after.sha256.json").read_text("utf-8"))["sha256"])
        self.assertTrue((outdir / "recovery_installed.sha256.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
