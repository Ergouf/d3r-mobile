"""Collect and validate a capture_android_battery.sh job after USB is reconnected."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_android_runtime as capture
import summarize_android_runtime as summarize


def decode_samples(raw: str, job: dict, start: dict) -> list[dict]:
    expected = capture.parse_proc_stat(job["proc_stat"])
    samples = []
    for block in raw.split("@@SAMPLE\n")[1:]:
        clock_text, rest = block.split("@@BATTERY\n", 1)
        battery_text, rest = rest.split("@@CURRENT\n", 1)
        current_text, rest = rest.split("@@PROC\n", 1)
        proc_text, end = rest.split("@@END", 1)
        if end.strip():
            raise ValueError("unexpected data after the sample terminator")
        clock = capture.parse_clock_helper(clock_text)
        battery = capture.parse_battery(battery_text)
        battery["current_now_ua"] = capture.parse_battery_current(current_text)
        battery["current_now_source"] = "batteryproperties.CURRENT_NOW"
        battery["current_now_status"] = "ok" if battery["current_now_ua"] is not None else "unsupported"
        voltage = re.search(r"(?m)^\s*voltage:\s*(\d+)\s*$", battery_text)
        if voltage:
            battery["voltage_mv"] = int(voltage.group(1))
        proc = capture.parse_proc_stat(proc_text.strip())
        if proc.pid != job["pid"] or proc.start_ticks != expected.start_ticks:
            raise ValueError("process identity changed within device-local capture")
        timestamp = clock["monotonic_s"] - start["monotonic_s"]
        if timestamp < 0 or samples and timestamp <= samples[-1]["timestamp_s"]:
            raise ValueError("non-monotonic sample timestamps")
        samples.append({
            "timestamp_s": timestamp, "device_monotonic_s": clock["monotonic_s"],
            "battery": battery,
            "identity": {"pid": proc.pid, "start_ticks": proc.start_ticks,
                         "apk_sha256": job["apk_sha256"]},
        })
    if not samples:
        raise ValueError("device-local capture contains no samples")
    return samples


def collect(job_file: Path, serial_override: str | None = None) -> dict | None:
    job = json.loads(job_file.read_text(encoding="utf-8"))
    serial = serial_override or job["serial"]
    capture.validate_serial(serial)
    capture.validate_package(job["package"])
    remote = job["remote"]
    if re.fullmatch(r"/data/local/tmp/d3-[A-Za-z0-9_-]+", remote) is None:
        raise ValueError("unexpected remote capture path")

    def read(name: str) -> bytes:
        return subprocess.check_output(["adb", "-s", serial, "exec-out", "cat", remote + "/" + name])

    status = read("status").decode().strip()
    if status == "running":
        print(f"Collector {job['collector_pid']} is still running at {remote}")
        return None
    folder = job_file.parent
    (folder / "status").write_text(status + "\n", encoding="utf-8")
    for name in ("samples.raw", "clock-start.json", "clock-end.json", "logcat.txt", "logcat.stderr.txt"):
        (folder / name).write_bytes(read(name))
    if status != "complete":
        raise ValueError("device-local collector stopped with status: " + status)
    start = capture.parse_clock_helper((folder / "clock-start.json").read_text())
    end = capture.parse_clock_helper((folder / "clock-end.json").read_text())
    samples = decode_samples((folder / "samples.raw").read_text(), job, start)
    if end["monotonic_s"] < samples[-1]["device_monotonic_s"]:
        raise ValueError("capture end precedes its last sample")
    (folder / "samples.jsonl").write_text(
        "".join(json.dumps(sample) + "\n" for sample in samples), encoding="utf-8")
    manifest = {
        "status": "complete", "package": job["package"], "start_pid": job["pid"],
        "start_ticks": capture.parse_proc_stat(job["proc_stat"]).start_ticks,
        "apk_sha256": job["apk_sha256"], "boot_id": job["boot_id"], "identity_changed": False,
        "capture_source": "device_local_shell", "sample_count": len(samples),
        "logcat_window": {"device_monotonic_start_s": start["monotonic_s"],
                          "device_monotonic_end_s": end["monotonic_s"],
                          "boot_id": job["boot_id"], "clock_status": "available"},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result = summarize.summarize_android_runtime(
        (folder / "logcat.txt").read_text(), [json.dumps(sample) for sample in samples], manifest=manifest)
    (folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--serial", help="override transport while retaining the captured identity")
    args = parser.parse_args()
    result = collect(args.job, args.serial)
    if result is None:
        return 2
    print(json.dumps({"fps": result.get("fps"), "samples": result.get("samples")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
