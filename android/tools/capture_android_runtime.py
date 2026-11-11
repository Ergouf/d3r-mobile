#!/usr/bin/env python3
"""Read-only Android runtime capture using an explicitly selected adb device."""

from __future__ import annotations

import argparse
import json
import math
import os
import posixpath
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


DEFAULT_PACKAGE = "com.d3mobile.host.validation"
PACKAGE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
CLOCK_HELPER_RE = re.compile(r"^/[A-Za-z0-9._+/-]+$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
BOOT_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


class CaptureFailure(Exception):
    def __init__(
        self,
        stage: str,
        message: str,
        *,
        stop_reason: str = "capture_error",
        identity_changed: bool = False,
        command: CommandResult | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.stop_reason = stop_reason
        self.identity_changed = identity_changed
        self.command = command


@dataclass(frozen=True)
class ProcStat:
    pid: int
    start_ticks: str
    utime_ticks: int
    stime_ticks: int


@dataclass(frozen=True)
class CommandResult:
    label: str
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_s: float
    timed_out: bool
    error: str | None


@dataclass
class ManagedLogcat:
    label: str
    argv: tuple[str, ...]
    process: object
    stdout_file: object
    stderr_file: object
    started_monotonic_s: float
    started_at_utc: str


class AdbRunner:
    """Run argv-only adb commands and manage one streaming logcat process."""

    def __init__(
        self,
        serial: str,
        timeout_s: float,
        command_log_path: Path,
        clock: Callable[[], float] = time.monotonic,
        popen_factory: Callable[..., object] | None = None,
    ) -> None:
        self.serial = serial
        self.timeout_s = timeout_s
        self._clock = clock
        self._popen_factory = popen_factory or subprocess.Popen
        self._sequence = 0
        self._command_log = command_log_path.open(
            "w", encoding="utf-8", buffering=1
        )

    def close(self) -> None:
        self._command_log.close()

    def run(
        self,
        label: str,
        remote_args: Sequence[str],
        *,
        record_stdout: bool = True,
    ) -> CommandResult:
        argv = ("adb", "-s", self.serial, *remote_args)
        started = self._clock()
        stdout = ""
        stderr = ""
        returncode: int | None = None
        timed_out = False
        error: str | None = None
        try:
            completed = subprocess.run(
                list(argv),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            returncode = completed.returncode
        except subprocess.TimeoutExpired as timeout_error:
            timed_out = True
            stdout = _timeout_text(timeout_error.stdout)
            stderr = _timeout_text(timeout_error.stderr)
            error = f"command timed out after {self.timeout_s:g}s"
        except OSError as os_error:
            error = str(os_error)
        elapsed_s = self._clock() - started
        result = CommandResult(
            label=label,
            argv=argv,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_s=elapsed_s,
            timed_out=timed_out,
            error=error,
        )
        self._record(result, record_stdout)
        return result

    def start_stream(
        self,
        label: str,
        remote_args: Sequence[str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> ManagedLogcat:
        argv = ("adb", "-s", self.serial, *remote_args)
        started_monotonic_s = self._clock()
        started_at_utc = _utc_now()
        stdout_file: object | None = None
        stderr_file: object | None = None
        try:
            stdout_file = stdout_path.open("w", encoding="utf-8", buffering=1)
            stderr_file = stderr_path.open("w", encoding="utf-8", buffering=1)
            process = self._popen_factory(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
        except Exception as start_error:
            _close_file_quietly(stdout_file)
            _close_file_quietly(stderr_file)
            self._append_record(
                {
                    "event": "start_failed",
                    "label": label,
                    "argv": list(argv),
                    "returncode": None,
                    "elapsed_s": self._clock() - started_monotonic_s,
                    "timed_out": False,
                    "error": str(start_error),
                    "stderr": "",
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                }
            )
            raise CaptureFailure(
                "logcat_stream",
                f"failed to start streaming logcat: {start_error}",
                stop_reason="logcat_stream_start_failed",
            ) from start_error

        managed = ManagedLogcat(
            label=label,
            argv=argv,
            process=process,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            started_monotonic_s=started_monotonic_s,
            started_at_utc=started_at_utc,
        )
        self._append_record(
            {
                "event": "started",
                "label": label,
                "argv": list(argv),
                "returncode": None,
                "elapsed_s": 0.0,
                "timed_out": False,
                "error": None,
                "stderr": "",
                "host_pid": getattr(process, "pid", None),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )
        return managed

    def stop_stream(self, managed: ManagedLogcat) -> dict[str, object]:
        initial_returncode = managed.process.poll()
        termination_requested = initial_returncode is None
        wait_timed_out = False
        errors: list[str] = []
        returncode = initial_returncode

        if termination_requested:
            try:
                managed.process.terminate()
            except Exception as terminate_error:
                errors.append(f"terminate failed: {terminate_error}")
                try:
                    managed.process.kill()
                except Exception as kill_error:
                    errors.append(f"kill failed: {kill_error}")
            try:
                returncode = managed.process.wait(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                wait_timed_out = True
                try:
                    managed.process.kill()
                except Exception as kill_error:
                    errors.append(f"kill failed after timeout: {kill_error}")
                try:
                    returncode = managed.process.wait(timeout=self.timeout_s)
                except subprocess.TimeoutExpired as timeout_error:
                    errors.append(f"wait failed after timeout: {timeout_error}")

        stdout_error = _flush_close_file(managed.stdout_file)
        stderr_error = _flush_close_file(managed.stderr_file)
        if stdout_error is not None:
            errors.append(stdout_error)
        if stderr_error is not None:
            errors.append(stderr_error)

        ended_monotonic_s = self._clock()
        unexpected_exit = initial_returncode is not None
        info: dict[str, object] = {
            "label": managed.label,
            "argv": list(managed.argv),
            "host_pid": getattr(managed.process, "pid", None),
            "started_at_utc": managed.started_at_utc,
            "ended_at_utc": _utc_now(),
            "elapsed_s": ended_monotonic_s - managed.started_monotonic_s,
            "returncode": returncode,
            "termination_requested": termination_requested,
            "terminate_wait_timed_out": wait_timed_out,
            "unexpected_exit": unexpected_exit,
            "stdout_path": str(managed.stdout_file.name),
            "stderr_path": str(managed.stderr_file.name),
            "errors": errors,
        }
        self._append_record(
            {
                "event": "stopped",
                "label": managed.label,
                "argv": list(managed.argv),
                "returncode": returncode,
                "elapsed_s": info["elapsed_s"],
                "timed_out": wait_timed_out,
                "error": "; ".join(errors) if errors else None,
                "stderr": "",
                "host_pid": info["host_pid"],
                "termination_requested": termination_requested,
                "unexpected_exit": unexpected_exit,
                "stdout_path": info["stdout_path"],
                "stderr_path": info["stderr_path"],
            }
        )
        return info

    def _record(self, result: CommandResult, record_stdout: bool) -> None:
        record: dict[str, object] = {
            "event": "completed",
            "label": result.label,
            "argv": list(result.argv),
            "returncode": result.returncode,
            "elapsed_s": result.elapsed_s,
            "timed_out": result.timed_out,
            "error": result.error,
            "stderr": result.stderr,
        }
        if record_stdout:
            record["stdout"] = result.stdout
        else:
            record["stdout_chars"] = len(result.stdout)
        self._append_record(record)

    def _append_record(self, record: dict[str, object]) -> None:
        self._sequence += 1
        record = {"sequence": self._sequence, **record}
        self._command_log.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._command_log.flush()


def _close_file_quietly(file: object | None) -> None:
    if file is None:
        return
    try:
        file.close()
    except Exception:
        pass


def _flush_close_file(file: object) -> str | None:
    error: str | None = None
    try:
        file.flush()
        try:
            os.fsync(file.fileno())
        except OSError:
            pass
        file.close()
    except Exception as flush_error:
        error = f"failed to flush/close stream file: {flush_error}"
        _close_file_quietly(file)
    return error

def _timeout_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_stream_running(managed: ManagedLogcat) -> None:
    returncode = managed.process.poll()
    if returncode is not None:
        raise CaptureFailure(
            "logcat_stream",
            f"streaming logcat exited early with returncode {returncode}",
            stop_reason="logcat_stream_exited",
        )


def _run_required(
    runner: AdbRunner,
    label: str,
    remote_args: Sequence[str],
    stage: str,
    *,
    record_stdout: bool = True,
) -> CommandResult:
    result = runner.run(label, remote_args, record_stdout=record_stdout)
    if result.timed_out:
        raise CaptureFailure(
            stage,
            f"{label} timed out",
            stop_reason="command_timeout",
            command=result,
        )
    if result.error is not None or result.returncode is None:
        raise CaptureFailure(
            stage,
            f"{label} failed: {result.error}",
            stop_reason="command_error",
            command=result,
        )
    if result.returncode != 0:
        raise CaptureFailure(
            stage,
            f"{label} returned {result.returncode}",
            stop_reason="command_failed",
            command=result,
        )
    return result


def validate_package(package: str) -> str:
    if not PACKAGE_RE.fullmatch(package):
        raise ValueError(
            "package must be a strict dotted Android package name"
        )
    return package


def validate_serial(serial: str) -> str:
    if not SERIAL_RE.fullmatch(serial):
        raise ValueError("serial contains unsupported characters")
    return serial


def validate_clock_helper(clock_helper: str | None) -> str | None:
    if clock_helper is None:
        return None
    if (
        not CLOCK_HELPER_RE.fullmatch(clock_helper)
        or posixpath.normpath(clock_helper) != clock_helper
        or posixpath.basename(clock_helper) in ("", ".", "/")
        or ".." in clock_helper.split("/")
    ):
        raise ValueError("clock helper must be a safe absolute device path")
    return clock_helper


def parse_pm_path(output: str) -> str:
    base_paths = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("package:"):
            continue
        path = line[len("package:") :]
        if posixpath.basename(path) == "base.apk":
            base_paths.append(path)
    if len(base_paths) != 1:
        raise ValueError("pm path must return exactly one base.apk path")
    apk_path = base_paths[0]
    if not posixpath.isabs(apk_path):
        raise ValueError("base.apk path is not absolute")
    if "\x00" in apk_path or "\n" in apk_path or "\r" in apk_path:
        raise ValueError("base.apk path contains an unsafe character")
    return apk_path


def parse_sha256(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("sha256sum output must contain exactly one line")
    parts = lines[0].split(None, 1)
    if not parts or not SHA256_RE.fullmatch(parts[0]):
        raise ValueError("sha256sum did not return a SHA-256 digest")
    if len(parts) != 2:
        raise ValueError("sha256sum output is missing the file path")
    return parts[0].lower()


def parse_pidof(output: str) -> int:
    tokens = output.split()
    if len(tokens) != 1 or not tokens[0].isdigit():
        raise ValueError("pidof must return exactly one numeric PID")
    pid = int(tokens[0])
    if pid <= 0:
        raise ValueError("pidof returned an invalid PID")
    return pid


def parse_proc_stat(output: str) -> ProcStat:
    text = output.strip()
    closing_parenthesis = text.rfind(")")
    if closing_parenthesis <= 0:
        raise ValueError("proc stat is missing the comm closing parenthesis")
    prefix = text[:closing_parenthesis]
    pid_token = prefix.split(None, 1)[0]
    if not pid_token.isdigit():
        raise ValueError("proc stat PID is invalid")
    fields = text[closing_parenthesis + 1 :].split()
    if len(fields) < 20:
        raise ValueError("proc stat has fewer than 22 fields")
    utime_ticks = int(fields[11])
    stime_ticks = int(fields[12])
    start_ticks = fields[19]
    if utime_ticks < 0 or stime_ticks < 0 or not start_ticks.isdigit():
        raise ValueError("proc stat timing fields are invalid")
    if int(start_ticks) <= 0:
        raise ValueError("proc stat start time is invalid")
    return ProcStat(
        pid=int(pid_token),
        start_ticks=start_ticks,
        utime_ticks=utime_ticks,
        stime_ticks=stime_ticks,
    )


def _parse_bool(value: str, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"invalid boolean for {field_name}")


def parse_battery(output: str) -> dict[str, object]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        name, value = raw_line.split(":", 1)
        values[name.strip().lower()] = value.strip()

    required = ("charge counter", "temperature", "usb powered")
    missing = [name for name in required if name not in values]
    if missing:
        raise ValueError("dumpsys battery missing: " + ", ".join(missing))

    charge_text = values["charge counter"]
    if not charge_text.isdigit():
        raise ValueError("Charge counter is not an integer")
    temperature_text = values["temperature"]
    if not _NUMBER_RE.fullmatch(temperature_text):
        raise ValueError("temperature is not numeric")
    temperature = float(temperature_text)
    if not math.isfinite(temperature):
        raise ValueError("temperature is not finite")

    usb_powered = _parse_bool(values["usb powered"], "USB powered")
    optional_fields: dict[str, bool | None] = {}
    for output_name, json_name in (
        ("ac powered", "ac_powered"),
        ("wireless powered", "wireless_powered"),
        ("dock powered", "dock_powered"),
    ):
        raw_value = values.get(output_name)
        optional_fields[json_name] = (
            _parse_bool(raw_value, output_name) if raw_value is not None else None
        )

    source_values = [usb_powered, *optional_fields.values()]
    if any(value is True for value in source_values):
        external_powered: bool | None = True
    elif all(isinstance(value, bool) for value in source_values):
        external_powered = False
    else:
        external_powered = None

    return {
        "charge_counter_uah": int(charge_text),
        "temperature_deci_c": temperature,
        "usb_powered": usb_powered,
        **optional_fields,
        "external_powered": external_powered,
    }


def parse_battery_current(output: str) -> int | None:
    """Decode IBatteryPropertiesRegistrar.getProperty(CURRENT_NOW), in microamps."""
    words: list[int] = []
    for line in output.splitlines():
        match = re.match(r"\s*0x([0-9a-fA-F]+):\s*([^']+)", line)
        if match is None:
            continue
        tokens = match.group(2).split()
        if int(match.group(1), 16) != len(words) * 4 or not 1 <= len(tokens) <= 4:
            raise ValueError("invalid battery property Parcel offsets")
        if any(re.fullmatch(r"[0-9a-fA-F]{8}", token) is None for token in tokens):
            raise ValueError("invalid battery property Parcel words")
        words.extend(int(token, 16) for token in tokens)
    if len(words) < 3 or words[0] != 0:
        raise ValueError("missing battery property Parcel or Binder exception")
    if words[1] != 0 or words[2] == 0:
        return None
    if words[2] != 1 or len(words) < 5:
        raise ValueError("incomplete battery property value")
    value = words[3] | (words[4] << 32)
    if value >= 1 << 63:
        value -= 1 << 64
    return None if value in (-(1 << 63), -(1 << 31)) else value


def read_battery_current(runner: AdbRunner) -> dict[str, object]:
    result = runner.run(
        "read_battery_current", ["shell", "service", "call", "batteryproperties", "1", "i32", "2"]
    )
    reading: dict[str, object] = {
        "current_now_ua": None,
        "current_now_source": "batteryproperties.CURRENT_NOW",
        "current_now_status": "unavailable",
    }
    if result.returncode != 0 or result.error or result.timed_out:
        return reading
    try:
        value = parse_battery_current(result.stdout)
    except ValueError as error:
        reading["current_now_status"] = "invalid_reply"
        reading["current_now_error"] = str(error)
        return reading
    reading["current_now_ua"] = value
    reading["current_now_status"] = "ok" if value is not None else "unsupported"
    return reading


def parse_boot_id(output: str) -> str:
    boot_id = output.strip()
    if not BOOT_ID_RE.fullmatch(boot_id):
        raise ValueError("boot_id is not a valid UUID")
    return boot_id.lower()


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def parse_clock_helper(output: str) -> dict[str, float]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError("clock helper did not return valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("clock helper JSON must be an object")
    result: dict[str, float] = {}
    for field_name in ("monotonic_s", "boottime_s", "realtime_s"):
        field_value = value.get(field_name)
        if not _is_finite_number(field_value) or float(field_value) < 0:
            raise ValueError(f"clock helper field {field_name} is invalid")
        result[field_name] = float(field_value)
    return result


def _value_or_failure(
    value: str,
    parser: Callable[[str], object],
    stage: str,
    stop_reason: str,
) -> object:
    try:
        return parser(value)
    except ValueError as error:
        raise CaptureFailure(
            stage,
            str(error),
            stop_reason=stop_reason,
        ) from error


def _read_clock_helper(
    runner: AdbRunner,
    clock_helper: str,
    label: str,
    stage: str,
) -> dict[str, float]:
    result = _run_required(
        runner,
        label,
        ["shell", clock_helper],
        stage,
    )
    return _value_or_failure(
        result.stdout,
        parse_clock_helper,
        stage,
        "device_clock_invalid",
    )


def _read_identity(
    runner: AdbRunner,
    package: str,
    expected_pid: int | None = None,
    expected_start_ticks: str | None = None,
) -> tuple[int, ProcStat]:
    pid_output = _run_required(
        runner,
        "read_pid",
        ["shell", "pidof", package],
        "identity_check",
    )
    pid = _value_or_failure(
        pid_output.stdout,
        parse_pidof,
        "identity_check",
        "identity_check_failed",
    )
    stat_output = _run_required(
        runner,
        "read_proc_stat",
        ["shell", "run-as", package, "cat", f"/proc/{pid}/stat"],
        "identity_check",
    )
    proc_stat = _value_or_failure(
        stat_output.stdout,
        parse_proc_stat,
        "identity_check",
        "identity_check_failed",
    )
    if proc_stat.pid != pid:
        raise CaptureFailure(
            "identity_check",
            "pidof and /proc stat PIDs differ",
            stop_reason="identity_changed",
            identity_changed=True,
        )
    if expected_pid is not None and pid != expected_pid:
        raise CaptureFailure(
            "identity_check",
            f"PID changed from {expected_pid} to {pid}",
            stop_reason="identity_changed",
            identity_changed=True,
        )
    if (
        expected_start_ticks is not None
        and proc_stat.start_ticks != expected_start_ticks
    ):
        raise CaptureFailure(
            "identity_check",
            "process start_ticks changed",
            stop_reason="identity_changed",
            identity_changed=True,
        )
    return pid, proc_stat


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_sample(file: object, sample: dict[str, object]) -> None:
    file.write(json.dumps(sample, ensure_ascii=False) + "\n")
    file.flush()


def capture_runtime(
    *,
    serial: str,
    package: str,
    duration_s: float,
    interval_s: float,
    output_dir: Path,
    clock_helper: str | None = None,
    cpu_ticks: bool = False,
    battery_current: bool = False,
    command_timeout_s: float = 15.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    popen_factory: Callable[..., object] | None = None,
) -> dict[str, object]:
    validate_package(package)
    validate_serial(serial)
    clock_helper = validate_clock_helper(clock_helper)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    capture_started_at = _utc_now()
    manifest: dict[str, object] = {
        "schema_version": 1,
        "status": "incomplete",
        "stop_reason": None,
        "identity_changed": False,
        "package": package,
        "serial": serial,
        "apk_path": None,
        "apk_sha256": None,
        "boot_id": None,
        "clock_helper": clock_helper,
        "start_pid": None,
        "start_ticks": None,
        "started_at_utc": capture_started_at,
        "ended_at_utc": None,
        "requested_duration_s": duration_s,
        "requested_interval_s": interval_s,
        "sample_count": 0,
        "cpu_ticks_collected": cpu_ticks,
        "battery_current_requested": battery_current,
        "timestamp_origin": (
            "host time.monotonic seconds relative to sample window start"
        ),
        "files": {
            "samples": "samples.jsonl",
            "commands": "commands.jsonl",
            "logcat": "logcat.txt",
            "logcat_stderr": "logcat.stderr.txt",
        },
        "limitations": [
            "This capture is not proof of game state correctness.",
            "This capture is not proof that 60 fps was achieved or that a "
            "60 fps target was met.",
            "total_us is host present-callback wall time, not complete game-frame time.",
        ],
        "errors": [],
    }
    errors: list[dict[str, object]] = []
    failure: CaptureFailure | None = None
    runner = AdbRunner(
        serial,
        command_timeout_s,
        output_dir / "commands.jsonl",
        clock=monotonic,
        popen_factory=popen_factory,
    )
    samples_path = output_dir / "samples.jsonl"
    samples_path.touch()
    logcat_path = output_dir / "logcat.txt"
    logcat_stderr_path = output_dir / "logcat.stderr.txt"
    logcat_path.touch()
    logcat_stderr_path.touch()
    managed_logcat: ManagedLogcat | None = None
    start_pid: int | None = None
    start_ticks: str | None = None
    sample_window_started_at: str | None = None
    sample_window_ended_at: str | None = None
    sample_monotonic_start: float | None = None
    sample_monotonic_end: float | None = None
    clock_start: dict[str, float] | None = None
    clock_end: dict[str, float] | None = None
    samples_written = 0

    try:
        pm_path_output = _run_required(
            runner,
            "resolve_base_apk",
            ["shell", "pm", "path", "--user", "0", package],
            "apk_path",
        )
        apk_path = _value_or_failure(
            pm_path_output.stdout,
            parse_pm_path,
            "apk_path",
            "apk_path_invalid",
        )
        manifest["apk_path"] = apk_path

        quoted_apk_path = shlex.quote(str(apk_path))
        sha_output = _run_required(
            runner,
            "hash_base_apk",
            ["shell", "sha256sum", quoted_apk_path],
            "apk_hash",
        )
        apk_sha256 = _value_or_failure(
            sha_output.stdout,
            parse_sha256,
            "apk_hash",
            "apk_hash_invalid",
        )
        manifest["apk_sha256"] = apk_sha256

        start_pid, start_stat = _read_identity(runner, package)
        start_ticks = start_stat.start_ticks
        manifest["start_pid"] = start_pid
        manifest["start_ticks"] = start_ticks

        boot_id_output = _run_required(
            runner,
            "read_boot_id",
            ["shell", "cat", "/proc/sys/kernel/random/boot_id"],
            "boot_id",
        )
        boot_id = _value_or_failure(
            boot_id_output.stdout,
            parse_boot_id,
            "boot_id",
            "boot_id_invalid",
        )
        manifest["boot_id"] = boot_id

        sample_window_started_at = _utc_now()
        sample_monotonic_start = monotonic()
        if clock_helper is not None:
            clock_start = _read_clock_helper(
                runner,
                clock_helper,
                "read_clock_helper_start",
                "device_window_start",
            )
        else:
            manifest["monotonic_clock_unavailable"] = True

        managed_logcat = runner.start_stream(
            "stream_logcat",
            [
                "logcat",
                f"--pid={start_pid}",
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
            logcat_path,
            logcat_stderr_path,
        )
        _ensure_stream_running(managed_logcat)

        deadline = sample_monotonic_start + duration_s
        with samples_path.open("a", encoding="utf-8", buffering=1) as sample_file:
            while True:
                now = monotonic()
                if now - deadline > 1e-9:
                    break
                _ensure_stream_running(managed_logcat)
                timestamp_s = now - sample_monotonic_start
                pid, proc_stat = _read_identity(
                    runner,
                    package,
                    expected_pid=start_pid,
                    expected_start_ticks=start_ticks,
                )

                battery_output = _run_required(
                    runner,
                    "read_battery",
                    ["shell", "dumpsys", "battery"],
                    "battery",
                )
                battery = _value_or_failure(
                    battery_output.stdout,
                    parse_battery,
                    "battery",
                    "battery_invalid",
                )
                if battery_current:
                    battery.update(read_battery_current(runner))

                process_data: dict[str, object] | None = None
                if cpu_ticks:
                    cpu_stat_output = _run_required(
                        runner,
                        "read_process_cpu_ticks",
                        ["shell", "run-as", package, "cat", f"/proc/{pid}/stat"],
                        "cpu_ticks",
                    )
                    cpu_stat = _value_or_failure(
                        cpu_stat_output.stdout,
                        parse_proc_stat,
                        "cpu_ticks",
                        "cpu_ticks_invalid",
                    )
                    if (
                        cpu_stat.pid != start_pid
                        or cpu_stat.start_ticks != start_ticks
                    ):
                        raise CaptureFailure(
                            "cpu_ticks",
                            "process identity changed while reading CPU ticks",
                            stop_reason="identity_changed",
                            identity_changed=True,
                        )
                    process_data = {
                        "utime_ticks": cpu_stat.utime_ticks,
                        "stime_ticks": cpu_stat.stime_ticks,
                        "source": f"/proc/{pid}/stat",
                    }

                _ensure_stream_running(managed_logcat)
                sample: dict[str, object] = {
                    "timestamp_s": timestamp_s,
                    "battery": battery,
                    "identity": {
                        "pid": pid,
                        "start_ticks": proc_stat.start_ticks,
                        "apk_sha256": apk_sha256,
                    },
                }
                if process_data is not None:
                    sample["process"] = process_data
                _write_sample(sample_file, sample)
                samples_written += 1
                manifest["sample_count"] = samples_written

                remaining_s = deadline - monotonic()
                if remaining_s <= 1e-9:
                    _ensure_stream_running(managed_logcat)
                    break
                sleep(min(interval_s, remaining_s))
    except CaptureFailure as capture_failure:
        failure = capture_failure
        error_record: dict[str, object] = {
            "stage": capture_failure.stage,
            "message": capture_failure.message,
            "stop_reason": capture_failure.stop_reason,
        }
        if capture_failure.command is not None:
            error_record["command"] = list(capture_failure.command.argv)
            error_record["returncode"] = capture_failure.command.returncode
            error_record["timed_out"] = capture_failure.command.timed_out
            error_record["stderr"] = capture_failure.command.stderr
        errors.append(error_record)
        manifest["identity_changed"] = capture_failure.identity_changed
    except Exception as unexpected_error:  # keep a manifest for operational failures
        failure = CaptureFailure(
            "unexpected",
            str(unexpected_error),
            stop_reason="unexpected_error",
        )
        errors.append(
            {
                "stage": failure.stage,
                "message": failure.message,
                "stop_reason": failure.stop_reason,
            }
        )
    finally:
        sample_monotonic_end = monotonic()
        sample_window_ended_at = _utc_now()

        if managed_logcat is not None:
            try:
                stream_info = runner.stop_stream(managed_logcat)
                stream_info["terminates_host_process_only"] = True
                manifest["logcat_stream"] = stream_info
                stream_errors = stream_info.get("errors", [])
                if stream_info.get("unexpected_exit") is True:
                    errors.append(
                        {
                            "stage": "logcat_stream",
                            "message": (
                                "streaming logcat exited before capture completion "
                                f"with returncode {stream_info.get('returncode')}"
                            ),
                            "stop_reason": "logcat_stream_exited",
                        }
                    )
                    if failure is None:
                        failure = CaptureFailure(
                            "logcat_stream",
                            "streaming logcat exited before capture completion",
                            stop_reason="logcat_stream_exited",
                        )
                elif stream_errors and failure is None:
                    failure = CaptureFailure(
                        "logcat_stream",
                        "streaming logcat cleanup failed",
                        stop_reason="logcat_stream_cleanup_failed",
                    )
            except Exception as stream_error:
                errors.append(
                    {
                        "stage": "logcat_stream",
                        "message": f"failed to stop streaming logcat: {stream_error}",
                        "stop_reason": "logcat_stream_stop_failed",
                    }
                )
                if failure is None:
                    failure = CaptureFailure(
                        "logcat_stream",
                        f"failed to stop streaming logcat: {stream_error}",
                        stop_reason="logcat_stream_stop_failed",
                    )
        else:
            manifest["logcat_stream"] = {
                "started": False,
                "reason": "identity was not established or stream failed to start",
            }

        if start_pid is not None and clock_helper is not None:
            try:
                clock_end = _read_clock_helper(
                    runner,
                    clock_helper,
                    "read_clock_helper_end",
                    "device_window_end",
                )
            except CaptureFailure as clock_failure:
                errors.append(
                    {
                        "stage": clock_failure.stage,
                        "message": clock_failure.message,
                        "stop_reason": clock_failure.stop_reason,
                    }
                )
                if failure is None:
                    failure = clock_failure
        monotonic_available = clock_start is not None and clock_end is not None
        if clock_helper is None:
            clock_status = "monotonic_clock_unavailable"
        elif monotonic_available:
            clock_status = "available"
        else:
            clock_status = "clock_helper_incomplete"
        manifest["monotonic_clock_unavailable"] = not monotonic_available
        manifest["device_clock"] = {
            "source": "ndk_helper" if clock_helper is not None else "unavailable",
            "helper": clock_helper,
            "status": clock_status,
            "start": clock_start,
            "end": clock_end,
        }
        manifest["logcat_window"] = {
            "start_utc": sample_window_started_at,
            "end_utc": sample_window_ended_at,
            "device_monotonic_start_s": (
                clock_start["monotonic_s"] if clock_start is not None else None
            ),
            "device_monotonic_end_s": (
                clock_end["monotonic_s"] if clock_end is not None else None
            ),
            "device_boottime_start_s": (
                clock_start["boottime_s"] if clock_start is not None else None
            ),
            "device_boottime_end_s": (
                clock_end["boottime_s"] if clock_end is not None else None
            ),
            "device_realtime_start_s": (
                clock_start["realtime_s"] if clock_start is not None else None
            ),
            "device_realtime_end_s": (
                clock_end["realtime_s"] if clock_end is not None else None
            ),
            "boot_id": manifest["boot_id"],
            "source": "streaming_logcat_stdout",
            "clock_status": clock_status,
            "monotonic_clock_unavailable": not monotonic_available,
            "raw_dump_includes_global_history": False,
            "filter_instruction": (
                "After verifying boot_id, retain logcat lines whose monotonic "
                "timestamps lie within the recorded start/end window."
            ),
        }
        manifest["host_monotonic_window"] = {
            "start_s": sample_monotonic_start,
            "end_s": sample_monotonic_end,
            "duration_s": (
                sample_monotonic_end - sample_monotonic_start
                if sample_monotonic_start is not None
                else None
            ),
        }
        manifest["ended_at_utc"] = _utc_now()
        manifest["stop_reason"] = (
            failure.stop_reason if failure is not None else "duration_elapsed"
        )
        manifest["status"] = "complete" if failure is None else "incomplete"
        manifest["errors"] = errors
        runner.close()
        _write_json(output_dir / "manifest.json", manifest)

    return manifest


def _positive_finite(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only adb runtime capture for one explicit Android device."
        )
    )
    parser.add_argument("--serial", required=True)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--duration-s", type=_positive_finite, default=60.0)
    parser.add_argument("--interval-s", type=_positive_finite, default=2.0)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--clock-helper",
        help="optional absolute device path to the read-only NDK clocks helper",
    )
    parser.add_argument("--cpu-ticks", action="store_true")
    parser.add_argument(
        "--battery-current", action="store_true",
        help="query net battery current through batteryproperties; does not measure USB input power",
    )
    parser.add_argument(
        "--command-timeout-s",
        type=_positive_finite,
        default=15.0,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        validate_package(args.package)
        validate_serial(args.serial)
        validate_clock_helper(args.clock_helper)
        if args.output_dir.exists():
            parser.error("--output-dir must be a new directory")
        manifest = capture_runtime(
            serial=args.serial,
            package=args.package,
            duration_s=args.duration_s,
            interval_s=args.interval_s,
            output_dir=args.output_dir,
            clock_helper=args.clock_helper,
            cpu_ticks=args.cpu_ticks,
            battery_current=args.battery_current,
            command_timeout_s=args.command_timeout_s,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
