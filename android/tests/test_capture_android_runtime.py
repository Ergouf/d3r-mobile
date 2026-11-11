from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "capture_android_runtime.py"
)
SPEC = importlib.util.spec_from_file_location("capture_android_runtime", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


BOOT_ID = "01234567-89ab-cdef-0123-456789abcdef"
APK_SHA256 = "a" * 64
APK_PATH = "/data/app/~~abc==/com.example/base.apk"
PACKAGE = "com.d3mobile.host.validation"
CLOCK_HELPER = "/data/local/tmp/d3-clock-helper"


def make_proc_stat(
    pid: int = 123,
    start_ticks: str = "987654",
    utime: int = 111,
    stime: int = 222,
) -> str:
    fields = ["0"] * 40
    fields[10] = str(utime)
    fields[11] = str(stime)
    fields[18] = start_ticks
    return f"{pid} (D3 process (debug)) S " + " ".join(fields)


def battery_output(ac_powered: bool = False) -> str:
    return "\n".join(
        [
            "Current Battery Service state:",
            f"  AC powered: {str(ac_powered).lower()}",
            "  USB powered: false",
            "  Wireless powered: false",
            "  Dock powered: false",
            "  Charge counter: 1000000",
            "  temperature: 350",
        ]
    )


BATTERY_CURRENT_PARCEL = """Result: Parcel(
0x00000000: 00000000 00000000 00000001 fffe42b0 '.............B..'
0x00000010: ffffffff ffffffff                   '........        ')
"""


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeAdb:
    def __init__(self, *, change_start_ticks: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.stat_count = 0
        self.clock_reads = 0
        self.change_start_ticks = change_start_ticks

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        remote = argv[3:]
        stdout = ""
        if remote[:4] == ["shell", "pm", "path", "--user"]:
            stdout = f"package:{APK_PATH}\n"
        elif remote[:2] == ["shell", "sha256sum"]:
            stdout = f"{APK_SHA256}  {APK_PATH}\n"
        elif remote[:3] == ["shell", "pidof", PACKAGE]:
            stdout = "123\n"
        elif remote[:4] == ["shell", "run-as", PACKAGE, "cat"]:
            self.stat_count += 1
            start_ticks = "123456" if self.change_start_ticks and self.stat_count > 1 else "987654"
            stdout = make_proc_stat(start_ticks=start_ticks) + "\n"
        elif remote == ["shell", "cat", "/proc/sys/kernel/random/boot_id"]:
            stdout = BOOT_ID + "\n"
        elif remote == ["shell", CLOCK_HELPER]:
            self.clock_reads += 1
            offset = (self.clock_reads - 1) * 0.2
            stdout = json.dumps(
                {
                    "monotonic_s": 31309.709 + offset,
                    "boottime_s": 31937.190 + offset,
                    "realtime_s": 1770000000.0 + offset,
                }
            ) + "\n"
        elif remote == ["shell", "dumpsys", "battery"]:
            stdout = battery_output() + "\n"
        elif remote == ["shell", "service", "call", "batteryproperties", "1", "i32", "2"]:
            stdout = BATTERY_CURRENT_PARCEL
        elif remote and remote[0] == "logcat":
            stdout = (
                "11-10 10:00:00.000 I/d3gpu: game frames=100 fps=50 "
                "interval=2.000s\n"
            )
        else:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unknown mock command")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


class FakeLogcatProcess:
    def __init__(
        self,
        *,
        early_returncode: int | None = None,
        ignore_terminate: bool = False,
    ) -> None:
        self.pid = 9001
        self.returncode = early_returncode
        self.ignore_terminate = ignore_terminate
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.ignore_terminate and not self.killed:
            raise subprocess.TimeoutExpired("adb", timeout)
        return int(self.returncode if self.returncode is not None else 0)


class FakeLogcatFactory:
    def __init__(
        self,
        *,
        early_returncode: int | None = None,
        ignore_terminate: bool = False,
    ) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.process = FakeLogcatProcess(
            early_returncode=early_returncode,
            ignore_terminate=ignore_terminate,
        )
        self.stdout_text = (
            "[ 100.100] I/d3gpu: game frames=101 fps=50 interval=1.000s\n"
        )
        self.stderr_text = ""

    def __call__(self, argv: list[str], **kwargs: object) -> FakeLogcatProcess:
        self.calls.append((list(argv), kwargs))
        stdout = kwargs["stdout"]
        stderr = kwargs["stderr"]
        stdout.write(self.stdout_text)
        stdout.flush()
        stderr.write(self.stderr_text)
        stderr.flush()
        return self.process


class CaptureRuntimeTests(unittest.TestCase):
    def test_battery_current_decodes_signed_native_parcel(self) -> None:
        self.assertEqual(capture.parse_battery_current(BATTERY_CURRENT_PARCEL), -114000)
        charging = BATTERY_CURRENT_PARCEL.replace("fffe42b0", "000f4240").replace(
            "ffffffff ffffffff", "00000000 ffffffff"
        )
        self.assertEqual(capture.parse_battery_current(charging), 1000000)

    def test_battery_current_preserves_unsupported_values(self) -> None:
        unsupported = BATTERY_CURRENT_PARCEL.replace("00000000 00000000 00000001",
                                                     "00000000 ffffffff 00000001")
        self.assertIsNone(capture.parse_battery_current(unsupported))
        sentinel = BATTERY_CURRENT_PARCEL.replace("fffe42b0", "00000000").replace(
            "ffffffff ffffffff", "80000000 ffffffff"
        )
        self.assertIsNone(capture.parse_battery_current(sentinel))

    def test_battery_current_rejects_malformed_or_exception_replies(self) -> None:
        for text in ("Permission denied", BATTERY_CURRENT_PARCEL.splitlines()[1],
                     BATTERY_CURRENT_PARCEL.replace("0x00000010", "0x00000020"),
                     BATTERY_CURRENT_PARCEL.replace("00000000 00000000", "fffffffc 00000000")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                capture.parse_battery_current(text)

    def test_battery_current_query_failure_remains_optional(self) -> None:
        runner = mock.Mock()
        runner.run.return_value = mock.Mock(returncode=1, error=None, timed_out=False)
        reading = capture.read_battery_current(runner)
        self.assertIsNone(reading["current_now_ua"])
        self.assertEqual(reading["current_now_status"], "unavailable")

    def test_mocked_capture_records_battery_current_when_requested(self) -> None:
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "capture"
            with mock.patch.object(capture.subprocess, "run", side_effect=FakeAdb()):
                manifest = capture.capture_runtime(
                    serial="device:5555", package=PACKAGE, duration_s=0.1, interval_s=0.1,
                    output_dir=output, clock_helper=CLOCK_HELPER, battery_current=True,
                    monotonic=clock, sleep=clock.sleep, popen_factory=FakeLogcatFactory(),
                )
            samples = [json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()]
        self.assertEqual(manifest["status"], "complete")
        self.assertTrue(manifest["battery_current_requested"])
        self.assertTrue(all(sample["battery"]["current_now_ua"] == -114000 for sample in samples))

    def test_proc_stat_uses_last_parenthesis_and_field_22(self) -> None:
        parsed = capture.parse_proc_stat(make_proc_stat())

        self.assertEqual(parsed.pid, 123)
        self.assertEqual(parsed.start_ticks, "987654")
        self.assertEqual(parsed.utime_ticks, 111)
        self.assertEqual(parsed.stime_ticks, 222)

    def test_package_and_clock_helper_validation_reject_shell_metacharacters(self) -> None:
        self.assertEqual(capture.validate_package(PACKAGE), PACKAGE)
        self.assertEqual(
            capture.validate_clock_helper(CLOCK_HELPER), CLOCK_HELPER
        )
        with self.assertRaises(ValueError):
            capture.validate_package("com.example;rm -rf /")
        with self.assertRaises(ValueError):
            capture.validate_clock_helper("/data/local/tmp/clock;id")

    def test_battery_combines_external_power_sources(self) -> None:
        battery = capture.parse_battery(battery_output(ac_powered=True))

        self.assertEqual(battery["charge_counter_uah"], 1_000_000)
        self.assertEqual(battery["temperature_deci_c"], 350.0)
        self.assertFalse(battery["usb_powered"])
        self.assertTrue(battery["external_powered"])

    def test_mocked_capture_completes_without_real_adb(self) -> None:
        clock = FakeClock()
        fake_adb = FakeAdb()
        fake_logcat = FakeLogcatFactory()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "capture"
            with mock.patch.object(capture.subprocess, "run", side_effect=fake_adb):
                manifest = capture.capture_runtime(
                    serial="device:5555",
                    package=PACKAGE,
                    duration_s=0.2,
                    interval_s=0.1,
                    output_dir=output_dir,
                    clock_helper=CLOCK_HELPER,
                    cpu_ticks=True,
                    monotonic=clock,
                    sleep=clock.sleep,
                    popen_factory=fake_logcat,
                )

            self.assertEqual(manifest["status"], "complete")
            self.assertFalse(manifest["identity_changed"])
            self.assertEqual(manifest["start_pid"], 123)
            self.assertEqual(manifest["apk_sha256"], APK_SHA256)
            self.assertEqual(manifest["boot_id"], BOOT_ID)
            self.assertIsNotNone(manifest["logcat_window"]["start_utc"])
            self.assertIsNotNone(manifest["logcat_window"]["end_utc"])
            self.assertAlmostEqual(
                manifest["logcat_window"]["device_monotonic_start_s"], 31309.709
            )
            self.assertAlmostEqual(
                manifest["logcat_window"]["device_monotonic_end_s"], 31309.909
            )
            self.assertAlmostEqual(
                manifest["logcat_window"]["device_boottime_start_s"], 31937.190
            )
            self.assertAlmostEqual(
                manifest["logcat_window"]["device_boottime_start_s"]
                - manifest["logcat_window"]["device_monotonic_start_s"],
                627.481,
            )
            self.assertEqual(
                manifest["logcat_window"]["clock_status"], "available"
            )
            self.assertFalse(manifest["monotonic_clock_unavailable"])
            self.assertTrue(manifest["logcat_stream"]["termination_requested"])
            self.assertFalse(manifest["logcat_stream"]["unexpected_exit"])
            self.assertTrue(fake_logcat.process.terminated)
            self.assertIn("started_at_utc", manifest["logcat_stream"])
            self.assertIn("ended_at_utc", manifest["logcat_stream"])
            self.assertFalse(
                manifest["logcat_window"]["raw_dump_includes_global_history"]
            )

            samples = [
                json.loads(line)
                for line in (output_dir / "samples.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            timestamps = [sample["timestamp_s"] for sample in samples]
            self.assertEqual(len(timestamps), 3)
            for actual, expected in zip(timestamps, [0.0, 0.1, 0.2]):
                self.assertAlmostEqual(actual, expected)
            self.assertEqual(samples[0]["identity"]["pid"], 123)
            self.assertEqual(samples[0]["identity"]["start_ticks"], "987654")
            self.assertEqual(samples[0]["identity"]["apk_sha256"], APK_SHA256)
            self.assertFalse(samples[0]["battery"]["external_powered"])
            self.assertEqual(samples[0]["process"]["utime_ticks"], 111)
            self.assertEqual(samples[0]["process"]["stime_ticks"], 222)

            commands = [
                json.loads(line)
                for line in (output_dir / "commands.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertTrue(commands)
            self.assertTrue(all(command["argv"][:3] == ["adb", "-s", "device:5555"] for command in commands))
            stream_events = [
                command
                for command in commands
                if command["label"] == "stream_logcat"
            ]
            self.assertEqual(
                [event["event"] for event in stream_events],
                ["started", "stopped"],
            )
            self.assertEqual(
                stream_events[0]["argv"][3:],
                [
                    "logcat",
                    "--pid=123",
                    "-v",
                    "monotonic",
                    "-T",
                    "1",
                    "-s",
                    "d3gpu:I",
                    "D3Host:I",
                    "D3Recovery:I",
                    "d3input:I",
                    "*:S",
                ],
            )
            start_index = commands.index(stream_events[0])
            stop_index = commands.index(stream_events[1])
            sample_labels = [
                command["label"] for command in commands[start_index + 1 : stop_index]
            ]
            self.assertEqual(
                sample_labels,
                [
                    "read_pid",
                    "read_proc_stat",
                    "read_battery",
                    "read_process_cpu_ticks",
                ]
                * 3,
            )
            self.assertEqual(commands[-1]["label"], "read_clock_helper_end")
            self.assertFalse(any("-d" in command["argv"] for command in commands))
            self.assertIn(
                "d3gpu: game",
                (output_dir / "logcat.txt").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (output_dir / "logcat.stderr.txt").read_text(encoding="utf-8"),
                "",
            )
            self.assertTrue(fake_adb.calls)
            self.assertEqual(len(fake_logcat.calls), 1)

    def test_missing_clock_helper_never_fabricates_monotonic_window(self) -> None:
        clock = FakeClock()
        fake_adb = FakeAdb()
        fake_logcat = FakeLogcatFactory()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "capture"
            with mock.patch.object(capture.subprocess, "run", side_effect=fake_adb):
                manifest = capture.capture_runtime(
                    serial="serial123",
                    package=PACKAGE,
                    duration_s=0.1,
                    interval_s=0.05,
                    output_dir=output_dir,
                    monotonic=clock,
                    sleep=clock.sleep,
                    popen_factory=fake_logcat,
                )

            self.assertEqual(manifest["status"], "complete")
            self.assertTrue(manifest["monotonic_clock_unavailable"])
            self.assertEqual(
                manifest["logcat_window"]["clock_status"],
                "monotonic_clock_unavailable",
            )
            self.assertIsNone(
                manifest["logcat_window"]["device_monotonic_start_s"]
            )
            self.assertIsNone(manifest["logcat_window"]["device_monotonic_end_s"])
            self.assertIsNone(manifest["device_clock"]["start"])
            self.assertNotIn(
                CLOCK_HELPER,
                [arg for command in fake_adb.calls for arg in command],
            )

    def test_early_stream_exit_marks_capture_incomplete(self) -> None:
        clock = FakeClock()
        fake_adb = FakeAdb()
        fake_logcat = FakeLogcatFactory(early_returncode=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "capture"
            with mock.patch.object(capture.subprocess, "run", side_effect=fake_adb):
                manifest = capture.capture_runtime(
                    serial="serial123",
                    package=PACKAGE,
                    duration_s=0.2,
                    interval_s=0.1,
                    output_dir=output_dir,
                    clock_helper=CLOCK_HELPER,
                    monotonic=clock,
                    sleep=clock.sleep,
                    popen_factory=fake_logcat,
                )

            self.assertEqual(manifest["status"], "incomplete")
            self.assertEqual(manifest["stop_reason"], "logcat_stream_exited")
            self.assertTrue(manifest["logcat_stream"]["unexpected_exit"])
            self.assertFalse(manifest["logcat_stream"]["termination_requested"])
            self.assertEqual(manifest["sample_count"], 0)
            commands = [
                json.loads(line)
                for line in (output_dir / "commands.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertFalse(any("-d" in command["argv"] for command in commands))

    def test_start_ticks_change_marks_identity_changed_and_incomplete(self) -> None:
        clock = FakeClock()
        fake_adb = FakeAdb(change_start_ticks=True)
        fake_logcat = FakeLogcatFactory()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "capture"
            with mock.patch.object(capture.subprocess, "run", side_effect=fake_adb):
                manifest = capture.capture_runtime(
                    serial="serial123",
                    package=PACKAGE,
                    duration_s=0.1,
                    interval_s=0.05,
                    output_dir=output_dir,
                    clock_helper=CLOCK_HELPER,
                    monotonic=clock,
                    sleep=clock.sleep,
                    popen_factory=fake_logcat,
                )

            self.assertEqual(manifest["status"], "incomplete")
            self.assertTrue(manifest["identity_changed"])
            self.assertEqual(manifest["stop_reason"], "identity_changed")
            self.assertEqual(manifest["sample_count"], 0)
            self.assertEqual(
                (output_dir / "samples.jsonl").read_text(encoding="utf-8"), ""
            )
            self.assertGreaterEqual(
                (output_dir / "logcat.txt").stat().st_size,
                0,
            )
            self.assertTrue(fake_logcat.process.terminated)
            self.assertFalse(manifest["logcat_stream"]["unexpected_exit"])

    def test_command_timeout_preserves_incomplete_manifest(self) -> None:
        clock = FakeClock()
        fake_logcat = FakeLogcatFactory()

        def timeout_adb(argv: list[str], **kwargs: object) -> object:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "capture"
            with mock.patch.object(capture.subprocess, "run", side_effect=timeout_adb):
                manifest = capture.capture_runtime(
                    serial="serial123",
                    package=PACKAGE,
                    duration_s=0.1,
                    interval_s=0.05,
                    output_dir=output_dir,
                    clock_helper=CLOCK_HELPER,
                    monotonic=clock,
                    sleep=clock.sleep,
                    popen_factory=fake_logcat,
                )

            self.assertEqual(manifest["status"], "incomplete")
            self.assertEqual(manifest["stop_reason"], "command_timeout")
            commands = [
                json.loads(line)
                for line in (output_dir / "commands.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(commands), 1)
            self.assertTrue(commands[0]["timed_out"])
            self.assertIsNone(commands[0]["returncode"])
            self.assertEqual(fake_logcat.calls, [])

    def test_existing_output_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileExistsError):
                capture.capture_runtime(
                    serial="serial123",
                    package=PACKAGE,
                    duration_s=0.1,
                    interval_s=0.05,
                    output_dir=Path(temp_dir),
                )


if __name__ == "__main__":
    unittest.main()
