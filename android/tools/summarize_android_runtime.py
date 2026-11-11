#!/usr/bin/env python3
"""Summarize offline Android game-runtime logs and optional telemetry samples."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
_FPS_RE = re.compile(
    rf"(?<![\w-])d3gpu\b.*?\bgame\s+frames\s*=\s*(?P<frames>\d+)\s+"
    rf"fps\s*=\s*(?P<fps>[+-]?{_NUMBER})\s+"
    rf"interval\s*=\s*(?P<interval>[+-]?{_NUMBER})\s*s\b"
)
_FRAME_TIMING_HEADER_RE = re.compile(
    r"(?<![\w-])frame-timing\s+frame\s*=\s*(?P<frame>\d+)(?=\s|$)"
)
_FRAME_TIMING_FIELD_RE = re.compile(
    rf"\b(?P<name>frame_interval_us|fence_wait_us|cpu_us|gpu_wait_us|"
    rf"present_us|total_us|poll_fences)"
    rf"\s*=\s*(?P<value>[+-]?{_NUMBER})(?=\s|$)"
)
_FPS_CANDIDATE_RE = re.compile(r"(?<![\w-])d3gpu\b[^\r\n]*\bgame\s+frames\s*=")
_FRAME_TIMING_CANDIDATE_RE = re.compile(r"(?<![\w-])frame-timing\b")
_CACHE_SCAN_CANDIDATE_RE = re.compile(r"\bcache-scan:")
_CACHE_SCAN_HEADER_RE = re.compile(
    rf"^\s*(?P<timestamp>{_NUMBER})\s+(?P<pid>\d+)\s+\d+\s+"
    r"[VDIWEF]\s+.*?\bcache-scan:\s+"
)
_CACHE_SCAN_POINT_RE = re.compile(
    r"\bpages=(?P<pages>\d+)\s+changed=(?P<changed>\d+)\s+"
    r"us=(?P<us>\d+)\s+generation=(?P<generation>\d+)\s+"
    r"write-faults=(?P<write_faults>\d+)\s+"
    r"watch-misses=(?P<watch_misses>\d+)(?:\s|$)"
)
_CACHE_BATCH_FIELD_RE = re.compile(
    rf"\b(?P<name>batch_count|batch_total_us|batch_max_us|batch_begin_us|"
    rf"batch_pages|batch_changed)\s*=\s*"
    rf"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s|$)"
)
_CACHE_MODE_ASSIGNMENT_RE = re.compile(r"\bcache_mode\s*=\s*(?P<value>[^\s]+)")
_MONOTONIC_BRACKET_RE = re.compile(
    rf"^\s*\[\s*(?P<timestamp>{_NUMBER})\s*\]\s+"
)
_MONOTONIC_RAW_RE = re.compile(
    rf"^\s*(?P<timestamp>{_NUMBER})\s+\d+\s+\d+\s+[VDIWEFAS]\s+"
    r"[^\s:]+\s*:\s*"
)


@dataclass(frozen=True)
class FpsRecord:
    frame: int
    fps: float
    interval_s: float
    timestamp_s: float | None


@dataclass(frozen=True)
class FrameTimingRecord:
    frame: int
    cpu_us: float
    gpu_wait_us: float
    present_us: float
    total_us: float
    fence_wait_us: float | None
    poll_fences: int | None
    cache_mode: int | None
    frame_interval_us: int | None
    timestamp_s: float | None


@dataclass(frozen=True)
class CacheBatch:
    count: int
    total_us: int
    max_us: int
    begin_us: int
    pages: int
    changed: int


@dataclass(frozen=True)
class CacheScanRecord:
    timestamp_s: float
    pid: int
    pages: int
    changed: int
    us: int
    generation: int
    write_faults: int
    watch_misses: int
    cache_mode: int | None
    batch: CacheBatch | None
    batch_exclusion_reason: str | None


@dataclass
class LogcatParseResult:
    fps_records: list[FpsRecord]
    frame_timing_records: list[FrameTimingRecord]
    invalid_fps: int
    invalid_frame_timing: int
    warnings: list[str]
    invalid_timestamps: int = 0
    excluded_before_window: int = 0
    excluded_after_window: int = 0
    excluded_cross_window_start: int = 0
    cache_scan_records: list[CacheScanRecord] | None = None
    cache_scan_invalid_lines: int = 0
    cache_scan_excluded_pid: int = 0
    cache_scan_excluded_before_window: int = 0
    cache_scan_excluded_after_window: int = 0
    cache_scan_batch_exclusions: dict[str, int] | None = None


@dataclass(frozen=True)
class ManifestWindow:
    valid: bool
    manifest_present: bool
    start_s: float | None
    end_s: float | None
    boot_id: str | None
    capture_status: str | None
    identity_changed: bool
    error: str | None = None
    pid: int | None = None


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _empty_fps_summary() -> dict[str, object]:
    return {
        "count": 0,
        "min": None,
        "median": None,
        "max": None,
        "interval_weighted_mean": None,
    }


def _frame_timing_field_notes() -> dict[str, object]:
    return {
        "present_us": (
            "RequestComposite + WaitForComposite wall-clock stage; includes "
            "gpu_wait_us and must not be added to it or treated as frame time"
        ),
        "cpu_us": "callback-thread CPU time, not whole-process CPU time",
        "fence_wait_us": "independent fence-wait measurement; never add stages",
        "timing_components_are_not_additive": True,
    }


_COMPONENT_FIELDS = (
    "cpu_us",
    "gpu_wait_us",
    "present_us",
    "total_us",
    "fence_wait_us",
)


def _component_summary(
    values: Sequence[float],
    record_count: int,
) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "missing_count": record_count,
            "mean_us": None,
            "p50_us": None,
            "p95_us": None,
            "p99_us": None,
            "max_us": None,
            "percentile_method": "nearest-rank",
        }
    return {
        "count": len(values),
        "missing_count": record_count - len(values),
        "mean_us": sum(values) / len(values),
        "p50_us": nearest_rank(values, 50),
        "p95_us": nearest_rank(values, 95),
        "p99_us": nearest_rank(values, 99),
        "max_us": max(values),
        "percentile_method": "nearest-rank",
    }


def _summarize_components(
    records: Sequence[FrameTimingRecord],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for field_name in _COMPONENT_FIELDS:
        values = [
            float(value)
            for record in records
            if (value := getattr(record, field_name)) is not None
        ]
        result[field_name] = _component_summary(values, len(records))
    return result


def _summarize_poll_fences(
    records: Sequence[FrameTimingRecord],
) -> dict[str, object]:
    zero_count = sum(record.poll_fences == 0 for record in records)
    one_count = sum(record.poll_fences == 1 for record in records)
    missing_count = sum(record.poll_fences is None for record in records)
    mixed_mode = zero_count > 0 and one_count > 0
    if not records:
        mode_status = "no_records"
    elif mixed_mode:
        mode_status = "mixed"
    elif zero_count and not missing_count:
        mode_status = "zero_only"
    elif one_count and not missing_count:
        mode_status = "one_only"
    elif zero_count or one_count:
        mode_status = "incomplete"
    else:
        mode_status = "missing"
    return {
        "counts_by_value": {
            "0": zero_count,
            "1": one_count,
            "missing": missing_count,
        },
        "zero_count": zero_count,
        "one_count": one_count,
        "missing_count": missing_count,
        "mixed_mode": mixed_mode,
        "pure_mode_analysis_allowed": (
            not mixed_mode
            and missing_count == 0
            and ((zero_count > 0) ^ (one_count > 0))
        ),
        "mode_status": mode_status,
    }


def _empty_frame_timing_summary() -> dict[str, object]:
    return {
        "metric": None,
        "source_field": None,
        "count": 0,
        "p50_us": None,
        "p95_us": None,
        "p99_us": None,
        "max_us": None,
        "over_16_667_ms": 0,
        "over_33_334_ms": 0,
        "percentile_method": "nearest-rank",
        "records_without_frame_interval": 0,
        "components_us": {
            field_name: _component_summary([], 0)
            for field_name in _COMPONENT_FIELDS
        },
        "components_are_not_additive": True,
        "poll_fences": _summarize_poll_fences([]),
        "cache_modes": _summarize_cache_modes([]),
        "describes_complete_game_frame_time": None,
        "supports_native_composite_rate_analysis": False,
        "can_assert_60_fps": False,
        "field_notes": _frame_timing_field_notes(),
    }


def nearest_rank(values: Sequence[float], percentile: int) -> float | None:
    """Return the nearest-rank percentile for a finite, non-empty sequence."""
    if not values:
        return None
    if not 1 <= percentile <= 100:
        raise ValueError("percentile must be between 1 and 100")
    rank = max(1, math.ceil(percentile * len(values) / 100))
    return sorted(values)[rank - 1]


def parse_monotonic_timestamp(line: str) -> float | None:
    """Return a strict logcat monotonic prefix timestamp, or None."""
    for prefix_re in (_MONOTONIC_BRACKET_RE, _MONOTONIC_RAW_RE):
        match = prefix_re.match(line)
        if match is None:
            continue
        timestamp_s = float(match.group("timestamp"))
        if math.isfinite(timestamp_s) and timestamp_s >= 0:
            return timestamp_s
        return None
    return None


def parse_manifest_window(manifest: object | None) -> ManifestWindow:
    if manifest is None:
        return ManifestWindow(
            valid=False,
            manifest_present=False,
            start_s=None,
            end_s=None,
            boot_id=None,
            capture_status=None,
            identity_changed=False,
        )
    if not isinstance(manifest, dict):
        return ManifestWindow(
            valid=False,
            manifest_present=True,
            start_s=None,
            end_s=None,
            boot_id=None,
            capture_status=None,
            identity_changed=False,
            error="manifest must be a JSON object",
        )

    capture_status = manifest.get("status")
    status_text = capture_status if isinstance(capture_status, str) else None
    identity_changed = manifest.get("identity_changed") is True
    window = manifest.get("logcat_window")
    if not isinstance(window, dict):
        return ManifestWindow(
            valid=False,
            manifest_present=True,
            start_s=None,
            end_s=None,
            boot_id=None,
            capture_status=status_text,
            identity_changed=identity_changed,
            error="manifest.logcat_window is missing",
        )

    start_s = window.get("device_monotonic_start_s")
    end_s = window.get("device_monotonic_end_s")
    if not _is_finite_number(start_s) or not _is_finite_number(end_s):
        return ManifestWindow(
            valid=False,
            manifest_present=True,
            start_s=None,
            end_s=None,
            boot_id=None,
            capture_status=status_text,
            identity_changed=identity_changed,
            error="manifest logcat window timestamps are missing or invalid",
        )
    start_float = float(start_s)
    end_float = float(end_s)
    if start_float < 0 or end_float <= start_float:
        return ManifestWindow(
            valid=False,
            manifest_present=True,
            start_s=start_float,
            end_s=end_float,
            boot_id=None,
            capture_status=status_text,
            identity_changed=identity_changed,
            error="manifest logcat window must have 0 <= start < end",
        )
    boot_id = window.get("boot_id")
    pid_value = manifest.get("start_pid")
    pid = (
        pid_value
        if isinstance(pid_value, int)
        and not isinstance(pid_value, bool)
        and pid_value > 0
        else None
    )
    return ManifestWindow(
        valid=True,
        manifest_present=True,
        start_s=start_float,
        end_s=end_float,
        boot_id=boot_id if isinstance(boot_id, str) else None,
        capture_status=status_text,
        identity_changed=identity_changed,
        pid=pid,
    )


def _classify_record_window(
    timestamp_s: float | None,
    span_s: float,
    window: ManifestWindow | None,
) -> str:
    if window is None:
        return "include"
    if timestamp_s is None:
        return "invalid_timestamp"
    assert window.start_s is not None and window.end_s is not None
    if timestamp_s < window.start_s:
        return "before"
    if timestamp_s > window.end_s:
        return "after"
    if timestamp_s - span_s < window.start_s:
        return "crosses_start"
    return "include"


_BATCH_FIELD_NAMES = {
    "batch_count",
    "batch_total_us",
    "batch_max_us",
    "batch_begin_us",
    "batch_pages",
    "batch_changed",
}


def _increment(mapping: dict[str, int], key: str) -> None:
    mapping[key] = mapping.get(key, 0) + 1


def _parse_cache_mode(line: str) -> tuple[int | None, str | None]:
    matches = list(_CACHE_MODE_ASSIGNMENT_RE.finditer(line))
    if not matches:
        return None, None
    if len(matches) > 1:
        return None, "duplicate_cache_mode"
    raw_value = matches[0].group("value")
    if raw_value not in ("0", "1", "2"):
        return None, "invalid_cache_mode"
    return int(raw_value), None


def _summarize_cache_modes(values: Sequence[int | None]) -> dict[str, object]:
    counts = {
        "0": sum(value == 0 for value in values),
        "1": sum(value == 1 for value in values),
        "2": sum(value == 2 for value in values),
        "missing": sum(value is None for value in values),
    }
    observed_modes = [mode for mode in (0, 1, 2) if counts[str(mode)] > 0]
    mixed_mode = len(observed_modes) > 1
    if not values:
        mode_status = "no_records"
    elif mixed_mode:
        mode_status = "mixed"
    elif len(observed_modes) == 1 and counts["missing"] == 0:
        mode_status = f"{observed_modes[0]}_only"
    elif len(observed_modes) == 1:
        mode_status = "incomplete"
    elif counts["missing"] == len(values):
        mode_status = "missing"
    else:
        mode_status = "unknown"
    return {
        "counts_by_value": counts,
        "mixed_mode": mixed_mode,
        "pure_mode_analysis_allowed": (
            len(observed_modes) == 1 and counts["missing"] == 0
        ),
        "mode_status": mode_status,
    }


def _parse_cache_batch(line: str) -> tuple[CacheBatch | None, str | None]:
    fields: dict[str, float] = {}
    duplicate = False
    for match in _CACHE_BATCH_FIELD_RE.finditer(line):
        field_name = match.group("name")
        if field_name in fields:
            duplicate = True
            break
        fields[field_name] = float(match.group("value"))

    present_names = set(fields)
    if not present_names:
        return None, "missing_batch_fields"
    if present_names != _BATCH_FIELD_NAMES:
        return None, "partial_batch_fields"
    if duplicate:
        return None, "duplicate_batch_field"

    count = fields["batch_count"]
    if count <= 0 or not count.is_integer():
        return None, "invalid_batch_count"
    integer_fields = (
        "batch_total_us",
        "batch_max_us",
        "batch_begin_us",
        "batch_pages",
        "batch_changed",
    )
    if any(
        fields[field_name] < 0 or not fields[field_name].is_integer()
        for field_name in integer_fields
    ):
        return None, "invalid_batch_value"
    return (
        CacheBatch(
            count=int(count),
            total_us=int(fields["batch_total_us"]),
            max_us=int(fields["batch_max_us"]),
            begin_us=int(fields["batch_begin_us"]),
            pages=int(fields["batch_pages"]),
            changed=int(fields["batch_changed"]),
        ),
        None,
    )


def parse_logcat(
    text: str,
    window: ManifestWindow | None = None,
) -> LogcatParseResult:
    fps_records: list[FpsRecord] = []
    frame_records: list[FrameTimingRecord] = []
    invalid_fps = 0
    invalid_frame_timing = 0
    invalid_timestamps = 0
    excluded_before_window = 0
    excluded_after_window = 0
    excluded_cross_window_start = 0
    cache_scan_records: list[CacheScanRecord] = []
    cache_scan_invalid_lines = 0
    cache_scan_excluded_pid = 0
    cache_scan_excluded_before_window = 0
    cache_scan_excluded_after_window = 0
    cache_scan_batch_exclusions: dict[str, int] = {}
    warnings: list[str] = []
    bounded = window is not None and window.valid

    def add_filter_warning(line_number: int, reason: str) -> None:
        nonlocal excluded_before_window
        nonlocal excluded_after_window
        nonlocal excluded_cross_window_start
        if reason == "before":
            excluded_before_window += 1
        elif reason == "after":
            excluded_after_window += 1
        elif reason == "crosses_start":
            excluded_cross_window_start += 1
            warnings.append(
                f"logcat line {line_number}: discarded record crossing window start"
            )

    for line_number, line in enumerate(text.splitlines(), start=1):
        timestamp_s = parse_monotonic_timestamp(line)
        is_fps_candidate = _FPS_CANDIDATE_RE.search(line) is not None
        is_frame_candidate = _FRAME_TIMING_CANDIDATE_RE.search(line) is not None
        is_cache_candidate = _CACHE_SCAN_CANDIDATE_RE.search(line) is not None
        if (
            bounded
            and (is_fps_candidate or is_frame_candidate or is_cache_candidate)
            and timestamp_s is None
        ):
            invalid_timestamps += 1
            warnings.append(
                f"logcat line {line_number}: invalid monotonic timestamp"
            )
            continue

        if is_fps_candidate:
            match = _FPS_RE.search(line)
            if match is None:
                invalid_fps += 1
                warnings.append(f"logcat line {line_number}: invalid fps record")
                continue
            fps = float(match.group("fps"))
            interval_s = float(match.group("interval"))
            if not math.isfinite(fps) or fps < 0 or interval_s <= 0:
                invalid_fps += 1
                warnings.append(f"logcat line {line_number}: invalid fps record")
                continue
            window_status = _classify_record_window(
                timestamp_s,
                interval_s,
                window if bounded else None,
            )
            if window_status != "include":
                add_filter_warning(line_number, window_status)
                continue
            fps_records.append(
                FpsRecord(
                    frame=int(match.group("frames")),
                    fps=fps,
                    interval_s=interval_s,
                    timestamp_s=timestamp_s,
                )
            )

        if is_frame_candidate:
            header = _FRAME_TIMING_HEADER_RE.search(line)
            fields: dict[str, float] = {}
            duplicate_field = False
            if header is not None:
                for field_match in _FRAME_TIMING_FIELD_RE.finditer(line):
                    name = field_match.group("name")
                    if name in fields:
                        duplicate_field = True
                        break
                    fields[name] = float(field_match.group("value"))

            required_fields = {"cpu_us", "gpu_wait_us", "present_us", "total_us"}
            if header is None or duplicate_field or not required_fields <= fields.keys():
                invalid_frame_timing += 1
                warnings.append(
                    f"logcat line {line_number}: invalid frame-timing record"
                )
                continue
            if any(not math.isfinite(value) or value < 0 for value in fields.values()):
                invalid_frame_timing += 1
                warnings.append(
                    f"logcat line {line_number}: invalid frame-timing record"
                )
                continue
            frame_interval = fields.get("frame_interval_us")
            if frame_interval is not None and frame_interval <= 0:
                invalid_frame_timing += 1
                warnings.append(
                    f"logcat line {line_number}: invalid frame_interval_us"
                )
                continue
            poll_fences_value = fields.get("poll_fences")
            if poll_fences_value is not None and (
                not float(poll_fences_value).is_integer()
                or int(poll_fences_value) not in (0, 1)
            ):
                invalid_frame_timing += 1
                warnings.append(
                    f"logcat line {line_number}: invalid poll_fences"
                )
                continue
            cache_mode, cache_mode_error = _parse_cache_mode(line)
            if cache_mode_error is not None:
                invalid_frame_timing += 1
                warnings.append(
                    f"logcat line {line_number}: {cache_mode_error}"
                )
                continue
            frame_interval_us = (
                int(frame_interval) if frame_interval is not None else None
            )
            interval_span_s = (
                frame_interval_us / 1_000_000.0
                if frame_interval_us is not None
                else 0.0
            )
            window_status = _classify_record_window(
                timestamp_s,
                interval_span_s,
                window if bounded else None,
            )
            if window_status != "include":
                add_filter_warning(line_number, window_status)
                continue
            frame_records.append(
                FrameTimingRecord(
                    frame=int(header.group("frame")),
                    cpu_us=fields["cpu_us"],
                    gpu_wait_us=fields["gpu_wait_us"],
                    present_us=fields["present_us"],
                    total_us=fields["total_us"],
                    fence_wait_us=fields.get("fence_wait_us"),
                    poll_fences=(
                        int(poll_fences_value)
                        if poll_fences_value is not None
                        else None
                    ),
                    cache_mode=cache_mode,
                    frame_interval_us=frame_interval_us,
                    timestamp_s=timestamp_s,
                )
            )

        if is_cache_candidate:
            cache_header = _CACHE_SCAN_HEADER_RE.match(line)
            cache_point = _CACHE_SCAN_POINT_RE.search(line)
            if cache_header is None or cache_point is None:
                cache_scan_invalid_lines += 1
                warnings.append(f"logcat line {line_number}: invalid cache-scan record")
                continue

            cache_timestamp_s = float(cache_header.group("timestamp"))
            cache_pid = int(cache_header.group("pid"))
            cache_mode, cache_mode_error = _parse_cache_mode(line)
            if cache_mode_error is not None:
                cache_scan_invalid_lines += 1
                warnings.append(
                    f"logcat line {line_number}: {cache_mode_error}"
                )
                continue
            if bounded:
                assert window.start_s is not None and window.end_s is not None
                if window.pid is not None and cache_pid != window.pid:
                    cache_scan_excluded_pid += 1
                    continue
                if cache_timestamp_s < window.start_s:
                    cache_scan_excluded_before_window += 1
                    continue
                if cache_timestamp_s > window.end_s:
                    cache_scan_excluded_after_window += 1
                    continue

            batch, batch_exclusion_reason = _parse_cache_batch(line)
            if batch is not None and bounded:
                assert window.start_s is not None
                batch_begin_s = batch.begin_us / 1_000_000.0
                if batch_begin_s < window.start_s:
                    batch = None
                    batch_exclusion_reason = "batch_starts_before_window"
                elif batch_begin_s > cache_timestamp_s:
                    batch = None
                    batch_exclusion_reason = "batch_begins_after_log_line"
            if batch_exclusion_reason is not None:
                _increment(cache_scan_batch_exclusions, batch_exclusion_reason)

            cache_scan_records.append(
                CacheScanRecord(
                    timestamp_s=cache_timestamp_s,
                    pid=cache_pid,
                    pages=int(cache_point.group("pages")),
                    changed=int(cache_point.group("changed")),
                    us=int(cache_point.group("us")),
                    generation=int(cache_point.group("generation")),
                    write_faults=int(cache_point.group("write_faults")),
                    watch_misses=int(cache_point.group("watch_misses")),
                    cache_mode=cache_mode,
                    batch=batch,
                    batch_exclusion_reason=batch_exclusion_reason,
                )
            )

    return LogcatParseResult(
        fps_records=fps_records,
        frame_timing_records=frame_records,
        invalid_fps=invalid_fps,
        invalid_frame_timing=invalid_frame_timing,
        warnings=warnings,
        invalid_timestamps=invalid_timestamps,
        excluded_before_window=excluded_before_window,
        excluded_after_window=excluded_after_window,
        excluded_cross_window_start=excluded_cross_window_start,
        cache_scan_records=cache_scan_records,
        cache_scan_invalid_lines=cache_scan_invalid_lines,
        cache_scan_excluded_pid=cache_scan_excluded_pid,
        cache_scan_excluded_before_window=cache_scan_excluded_before_window,
        cache_scan_excluded_after_window=cache_scan_excluded_after_window,
        cache_scan_batch_exclusions=cache_scan_batch_exclusions,
    )

def summarize_fps(records: Sequence[FpsRecord]) -> dict[str, object]:
    if not records:
        return _empty_fps_summary()
    values = [record.fps for record in records]
    total_interval = sum(record.interval_s for record in records)
    weighted_mean = sum(
        record.fps * record.interval_s for record in records
    ) / total_interval
    return {
        "count": len(records),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "interval_weighted_mean": weighted_mean,
    }


def summarize_frame_timing(
    records: Sequence[FrameTimingRecord],
) -> dict[str, object]:
    if not records:
        return _empty_frame_timing_summary()

    native_intervals = [
        record.frame_interval_us
        for record in records
        if record.frame_interval_us is not None
    ]
    if native_intervals:
        metric = "native_composite_interval"
        source_field = "frame_interval_us"
        values = [int(value) for value in native_intervals]
        describes_complete_frame = False
        supports_native_composite_rate_analysis = True
        records_without_frame_interval = len(records) - len(values)
    else:
        metric = "present_callback_wall"
        source_field = "total_us"
        values = [record.total_us for record in records]
        describes_complete_frame = False
        supports_native_composite_rate_analysis = False
        records_without_frame_interval = len(records)

    return {
        "metric": metric,
        "source_field": source_field,
        "count": len(values),
        "p50_us": int(nearest_rank(values, 50)),
        "p95_us": int(nearest_rank(values, 95)),
        "p99_us": int(nearest_rank(values, 99)),
        "max_us": max(values),
        "over_16_667_ms": sum(value > 16_667 for value in values),
        "over_33_334_ms": sum(value > 33_334 for value in values),
        "percentile_method": "nearest-rank",
        "records_without_frame_interval": records_without_frame_interval,
        "components_us": _summarize_components(records),
        "components_are_not_additive": True,
        "poll_fences": _summarize_poll_fences(records),
        "cache_modes": _summarize_cache_modes(
            [record.cache_mode for record in records]
        ),
        "describes_complete_game_frame_time": describes_complete_frame,
        "supports_native_composite_rate_analysis": (
            supports_native_composite_rate_analysis
        ),
        "can_assert_60_fps": False,
        "metric_note": (
            "Native composite cadence only. This log does not establish "
            "stable game or display 60 fps acceptance."
            if native_intervals
            else (
                "Host present-callback wall time only; this is not complete "
                "game-frame time and cannot establish stable game or display 60 fps."
            )
        ),
        "field_notes": _frame_timing_field_notes(),
    }


def _cache_distribution(values: Sequence[float]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
            "percentile_method": "nearest-rank",
        }
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": nearest_rank(values, 50),
        "p95": nearest_rank(values, 95),
        "p99": nearest_rank(values, 99),
        "max": max(values),
        "percentile_method": "nearest-rank",
    }


def _aggregate_cache_batches(batches: Sequence[CacheBatch]) -> dict[str, object]:
    total_scan_count = sum(batch.count for batch in batches)
    total_us = sum(batch.total_us for batch in batches)
    total_pages = sum(batch.pages for batch in batches)
    total_changed = sum(batch.changed for batch in batches)
    begin_values = [batch.begin_us for batch in batches]
    return {
        "batch_record_count": len(batches),
        "total_scan_count": total_scan_count,
        "total_us": total_us,
        "weighted_mean_us": (
            total_us / total_scan_count if total_scan_count else None
        ),
        "max_us": max((batch.max_us for batch in batches), default=None),
        "pages_per_scan_mean": (
            total_pages / total_scan_count if total_scan_count else None
        ),
        "changed_per_scan_mean": (
            total_changed / total_scan_count if total_scan_count else None
        ),
        "batch_begin_us_first": begin_values[0] if begin_values else None,
        "batch_begin_us_last": begin_values[-1] if begin_values else None,
        "max_semantics": (
            "Maximum of batch_max_us values; this is not a P99 estimate."
        ),
    }


def summarize_cache_scan(logcat: LogcatParseResult) -> dict[str, object]:
    records = logcat.cache_scan_records or []
    point_fields = {
        "pages": [record.pages for record in records],
        "changed": [record.changed for record in records],
        "us": [record.us for record in records],
        "generation": [record.generation for record in records],
        "write_faults": [record.write_faults for record in records],
        "watch_misses": [record.watch_misses for record in records],
    }
    cache_modes = _summarize_cache_modes(
        [record.cache_mode for record in records]
    )
    batches = [record.batch for record in records if record.batch is not None]
    by_cache_mode = {
        str(mode): _aggregate_cache_batches(
            [
                record.batch
                for record in records
                if record.cache_mode == mode and record.batch is not None
            ]
        )
        for mode in (0, 1, 2)
    }
    by_cache_mode["missing"] = _aggregate_cache_batches(
        [
            record.batch
            for record in records
            if record.cache_mode is None and record.batch is not None
        ]
    )

    mixed_mode = bool(cache_modes["mixed_mode"])
    pure_mode_analysis_allowed = bool(
        cache_modes["pure_mode_analysis_allowed"]
    )
    if pure_mode_analysis_allowed:
        batch_summary = _aggregate_cache_batches(batches)
        batch_summary["cross_mode_total_omitted"] = False
        batch_summary["aggregate_omitted_reason"] = None
    else:
        batch_summary = {
            "batch_record_count": len(batches),
            "total_scan_count": None,
            "total_us": None,
            "weighted_mean_us": None,
            "max_us": None,
            "pages_per_scan_mean": None,
            "changed_per_scan_mean": None,
            "batch_begin_us_first": None,
            "batch_begin_us_last": None,
            "cross_mode_total_omitted": True,
            "aggregate_omitted_reason": (
                "mixed_cache_mode"
                if mixed_mode
                else "missing_or_unconfirmed_cache_mode"
            ),
            "max_semantics": (
                "Cross-mode totals are omitted; batch_max_us is not a P99 estimate."
            ),
        }
    batch_summary["mixed_mode"] = mixed_mode
    batch_summary["pure_mode_analysis_allowed"] = pure_mode_analysis_allowed
    batch_summary["by_cache_mode"] = by_cache_mode
    batch_summary["method"] = (
        "Only complete batch_* records with batch_count > 0, batch start "
        "inside the manifest window, and batch start no later than the "
        "reporting log timestamp are aggregated. Mixed cache_mode totals are omitted."
    )

    return {
        "available": True,
        "cache_modes": cache_modes,
        "point_samples": {
            "count": len(records),
            "fields": {
                field_name: _cache_distribution(values)
                for field_name, values in point_fields.items()
            },
            "audit_bias_warning": (
                "Single-point cache-scan samples are audit-biased: they occur "
                "every 256 rounds and coincide with the full watch audit cadence; "
                "they are retained as audit evidence and must not estimate "
                "normal watch behavior."
            ),
        },
        "batches": batch_summary,
        "filter_counts": {
            "invalid_lines": logcat.cache_scan_invalid_lines,
            "excluded_pid": logcat.cache_scan_excluded_pid,
            "excluded_before_window": logcat.cache_scan_excluded_before_window,
            "excluded_after_window": logcat.cache_scan_excluded_after_window,
        },
        "batch_exclusions": dict(
            sorted((logcat.cache_scan_batch_exclusions or {}).items())
        ),
    }


def _unavailable_cache_scan(reason: str) -> dict[str, object]:
    return {
        "available": False,
        "reason": reason,
        "point_samples": None,
        "batches": None,
        "batch_exclusions": None,
    }


def _identity_fields(sample: dict[str, object]) -> dict[str, object]:
    identity = sample.get("identity")
    if not isinstance(identity, dict):
        return {}
    fields: dict[str, object] = {}
    pid = identity.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool):
        fields["pid"] = pid
    start_ticks = identity.get("start_ticks")
    if isinstance(start_ticks, str) and start_ticks:
        fields["start_ticks"] = start_ticks
    apk_sha256 = identity.get("apk_sha256")
    if isinstance(apk_sha256, str) and apk_sha256:
        fields["apk_sha256"] = apk_sha256
    return fields


_POWER_SOURCE_FIELDS = (
    "ac_powered",
    "usb_powered",
    "wireless_powered",
    "dock_powered",
)


def _external_power_state(record: dict[str, object]) -> bool | None:
    if "external_powered" in record:
        external_powered = record["external_powered"]
        return external_powered if isinstance(external_powered, bool) else None

    present_sources = {
        field_name: record[field_name]
        for field_name in _POWER_SOURCE_FIELDS
        if field_name in record
    }
    known_sources = {
        field_name: value
        for field_name, value in present_sources.items()
        if isinstance(value, bool)
    }
    if any(known_sources.values()):
        return True
    if len(known_sources) == len(_POWER_SOURCE_FIELDS):
        return False
    # Legacy samples supplied only usb_powered.
    if set(present_sources) == {"usb_powered"}:
        usb_powered = known_sources.get("usb_powered")
        return usb_powered if isinstance(usb_powered, bool) else None
    return None


def _summarize_sample_records(
    records: Sequence[dict[str, object]], invalid_count: int = 0
) -> dict[str, object]:
    temperatures = [
        float(record["temperature_deci_c"])
        for record in records
        if record.get("temperature_deci_c") is not None
    ]
    charge_records = [
        (float(record["timestamp_s"]), float(record["charge_counter_uah"]))
        for record in records
        if record.get("charge_counter_uah") is not None
    ]
    currents = [float(record["current_now_ua"]) for record in records
                if record.get("current_now_ua") is not None]

    first_timestamp = float(records[0]["timestamp_s"])
    last_timestamp = float(records[-1]["timestamp_s"])
    duration_s = last_timestamp - first_timestamp
    external_power_states = [_external_power_state(record) for record in records]
    charge_values = [record.get("charge_counter_uah") for record in records]

    charge_start = charge_records[0][1] if charge_records else None
    charge_end = charge_records[-1][1] if charge_records else None
    charge_change = (
        charge_end - charge_start
        if charge_start is not None and charge_end is not None
        else None
    )

    status = "ok"
    average_discharge_ma: float | None = None
    if len(records) < 2:
        status = "insufficient_samples"
    elif duration_s < 0:
        status = "non_monotonic_timestamps"
    elif duration_s == 0:
        status = "zero_duration"
    elif any(state is True for state in external_power_states):
        status = "charging"
    elif invalid_count:
        status = "invalid_sample_records"
    elif any(not isinstance(state, bool) for state in external_power_states):
        status = "missing_external_power_state"
    elif any(value is None for value in charge_values):
        status = "missing_charge"
    elif charge_start is None or charge_end is None:
        status = "missing_charge"
    elif charge_start - charge_end < 0:
        status = "charge_increased"
    else:
        average_discharge_ma = (
            (charge_start - charge_end) / 1000.0 / (duration_s / 3600.0)
        )

    return {
        "temperature_deci_c": {
            "count": len(temperatures),
            "min": min(temperatures) if temperatures else None,
            "max": max(temperatures) if temperatures else None,
        },
        "charge_counter_uah": {
            "observation_count": len(charge_records),
            "start": charge_start,
            "end": charge_end,
            "change_uah": charge_change,
        },
        "first_timestamp_s": first_timestamp,
        "last_timestamp_s": last_timestamp,
        "duration_s": duration_s,
        "external_power": {
            "observation_count": sum(
                isinstance(state, bool) for state in external_power_states
            ),
            "powered_count": sum(
                state is True for state in external_power_states
            ),
            "unpowered_count": sum(
                state is False for state in external_power_states
            ),
            "source_true_counts": {
                field_name: sum(
                    record.get(field_name) is True for record in records
                )
                for field_name in _POWER_SOURCE_FIELDS
            },
            "external_powered_true_counts": sum(
                record.get("external_powered") is True for record in records
            ),
        },
        "average_discharge_ma": average_discharge_ma,
        "average_discharge_status": status,
        "battery_net_current_ua": {
            "count": len(currents),
            "min": min(currents) if currents else None,
            "max": max(currents) if currents else None,
            "sample_mean": sum(currents) / len(currents) if currents else None,
            "scope": "net battery current; excludes external input power",
            "sign": "positive charging, negative discharging",
        },
    }


def summarize_samples(
    lines: Iterable[str],
) -> tuple[dict[str, object] | None, int, list[str]]:
    """Parse JSONL samples and return (summary, invalid_count, warnings)."""
    records: list[dict[str, object]] = []
    invalid_count = 0
    warnings: list[str] = []
    missing_temperature = 0
    missing_charge = 0
    missing_usb = 0
    missing_power_state = 0
    incomplete_identity = 0
    identity_values: dict[str, set[object]] = {
        "pid": set(),
        "start_ticks": set(),
        "apk_sha256": set(),
    }

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            sample = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            warnings.append(f"samples line {line_number}: invalid JSON record")
            continue
        if not isinstance(sample, dict):
            invalid_count += 1
            warnings.append(
                f"samples line {line_number}: sample must be a JSON object"
            )
            continue

        timestamp = sample.get("timestamp_s")
        if not _is_finite_number(timestamp):
            invalid_count += 1
            warnings.append(f"samples line {line_number}: invalid timestamp_s")
            continue

        record: dict[str, object] = {"timestamp_s": float(timestamp)}
        battery = sample.get("battery")
        if not isinstance(battery, dict):
            missing_temperature += 1
            missing_charge += 1
            missing_usb += 1
            missing_power_state += 1
        else:
            temperature = battery.get("temperature_deci_c")
            if _is_finite_number(temperature):
                record["temperature_deci_c"] = float(temperature)
            else:
                missing_temperature += 1

            charge = battery.get("charge_counter_uah")
            if _is_finite_number(charge):
                record["charge_counter_uah"] = float(charge)
            else:
                missing_charge += 1

            current = battery.get("current_now_ua")
            if _is_finite_number(current):
                record["current_now_ua"] = float(current)

            usb_powered = battery.get("usb_powered")
            if isinstance(usb_powered, bool):
                record["usb_powered"] = usb_powered
            else:
                missing_usb += 1

            for field_name in (
                "ac_powered",
                "wireless_powered",
                "dock_powered",
                "external_powered",
            ):
                if field_name not in battery:
                    continue
                field_value = battery[field_name]
                record[field_name] = (
                    field_value if isinstance(field_value, bool) else None
                )

            if _external_power_state(record) is None:
                missing_power_state += 1

        identity_fields = _identity_fields(sample)
        if len(identity_fields) != 3:
            incomplete_identity += 1
        for field_name, value in identity_fields.items():
            identity_values[field_name].add(value)
        records.append(record)

    if not records and invalid_count == 0:
        return None, 0, warnings
    if not records:
        return (
            {
                "count": 0,
                "invalid_count": invalid_count,
                "identity_changed": False,
                "identity_status": "unavailable",
                "identity_changed_fields": [],
                "identity": {
                    "complete_sample_count": 0,
                    "incomplete_sample_count": 0,
                    "distinct_value_counts": {
                        "pid": 0,
                        "start_ticks": 0,
                        "apk_sha256": 0,
                    },
                },
                "missing_counts": {
                    "temperature_deci_c": 0,
                    "charge_counter_uah": 0,
                    "usb_powered": 0,
                    "identity": 0,
                },
                "temperature_deci_c": {"count": 0, "min": None, "max": None},
                "charge_counter_uah": {
                    "observation_count": 0,
                    "start": None,
                    "end": None,
                    "change_uah": None,
                },
                "first_timestamp_s": None,
                "last_timestamp_s": None,
                "duration_s": None,
                "average_discharge_ma": None,
                "average_discharge_status": "insufficient_samples",
            },
            invalid_count,
            warnings,
        )

    changed_fields = [
        field_name
        for field_name, values in identity_values.items()
        if len(values) > 1
    ]
    observed_identity_values = sum(len(values) for values in identity_values.values())
    identity_changed = bool(changed_fields)
    if identity_changed:
        identity_status = "changed"
        warnings.append(
            "sample identity changed; combined battery metrics and frame statistics omitted"
        )
    elif observed_identity_values:
        identity_status = "consistent"
    else:
        identity_status = "unavailable"

    if incomplete_identity:
        warnings.append(
            f"{incomplete_identity} sample(s) have incomplete or invalid identity fields"
        )
    if missing_temperature:
        warnings.append(
            f"{missing_temperature} sample(s) have missing or invalid temperature_deci_c"
        )
    if missing_charge:
        warnings.append(
            f"{missing_charge} sample(s) have missing or invalid charge_counter_uah"
        )
    if missing_usb:
        warnings.append(
            f"{missing_usb} sample(s) have missing or invalid usb_powered"
        )
    if missing_power_state:
        warnings.append(
            f"{missing_power_state} sample(s) have no decisive external power state"
        )

    summary: dict[str, object] = {
        "count": len(records),
        "invalid_count": invalid_count,
        "identity_changed": identity_changed,
        "identity_status": identity_status,
        "identity_changed_fields": changed_fields,
        "identity": {
            "complete_sample_count": len(records) - incomplete_identity,
            "incomplete_sample_count": incomplete_identity,
            "distinct_value_counts": {
                field_name: len(values)
                for field_name, values in identity_values.items()
            },
        },
        "missing_counts": {
            "temperature_deci_c": missing_temperature,
            "charge_counter_uah": missing_charge,
            "usb_powered": missing_usb,
            "external_power_state": missing_power_state,
            "identity": incomplete_identity,
        },
    }

    if identity_changed:
        summary.update(
            {
                "temperature_deci_c": {"count": 0, "min": None, "max": None},
                "charge_counter_uah": {
                    "observation_count": 0,
                    "start": None,
                    "end": None,
                    "change_uah": None,
                },
                "first_timestamp_s": None,
                "last_timestamp_s": None,
                "duration_s": None,
                "average_discharge_ma": None,
                "average_discharge_status": "identity_changed",
                "aggregate_omitted_reason": "identity_changed",
            }
        )
    else:
        summary.update(_summarize_sample_records(records, invalid_count))

    return summary, invalid_count, warnings


def _logcat_scope_with_warnings(
    window: ManifestWindow,
) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    if not window.manifest_present:
        scope: dict[str, object] = {
            "mode": "unbounded_history",
            "bounded": False,
            "is_current_capture": False,
            "window_start_s": None,
            "window_end_s": None,
            "boot_id": None,
            "capture_status": None,
            "capture_complete": False,
            "identity_changed": False,
            "warning": (
                "No capture manifest was supplied. This is an unbounded-history "
                "analysis and must not be treated as a current capture report."
            ),
        }
        warnings.append(str(scope["warning"]))
        return scope, warnings

    if not window.valid:
        scope = {
            "mode": "invalid_manifest_window",
            "bounded": False,
            "is_current_capture": False,
            "window_start_s": window.start_s,
            "window_end_s": window.end_s,
            "boot_id": window.boot_id,
            "capture_status": window.capture_status,
            "capture_complete": False,
            "identity_changed": window.identity_changed,
            "error": window.error,
            "warning": (
                "Manifest logcat window is missing or invalid; full-history "
                "logcat statistics were refused."
            ),
        }
        warnings.append(str(scope["warning"]))
        return scope, warnings

    capture_status = window.capture_status or "unknown"
    scope = {
        "mode": "manifest_bounded",
        "bounded": True,
        "is_current_capture": True,
        "window_start_s": window.start_s,
        "window_end_s": window.end_s,
        "boot_id": window.boot_id,
        "capture_status": capture_status,
        "capture_complete": capture_status == "complete",
        "identity_changed": window.identity_changed,
        "warning": None,
    }
    if capture_status == "incomplete":
        scope["warning"] = (
            "Capture manifest status is incomplete; statistics are bounded to "
            "the recorded window but describe an incomplete capture."
        )
        warnings.append(str(scope["warning"]))
    elif capture_status != "complete":
        scope["warning"] = (
            f"Capture manifest status is {capture_status!r}; capture completeness "
            "is not established."
        )
        warnings.append(str(scope["warning"]))
    return scope, warnings


def summarize_android_runtime(
    logcat_text: str,
    sample_lines: Iterable[str] | None = None,
    manifest: object | None = None,
) -> dict[str, object]:
    manifest_window = parse_manifest_window(manifest)
    logcat_scope, warnings = _logcat_scope_with_warnings(manifest_window)

    invalid_manifest_window = manifest_window.manifest_present and not manifest_window.valid
    if invalid_manifest_window:
        logcat = LogcatParseResult(
            fps_records=[],
            frame_timing_records=[],
            invalid_fps=0,
            invalid_frame_timing=0,
            warnings=[],
        )
    else:
        logcat = parse_logcat(
            logcat_text,
            manifest_window if manifest_window.valid else None,
        )

    sample_summary: dict[str, object] | None = None
    invalid_samples = 0
    sample_warnings: list[str] = []
    if sample_lines is not None:
        sample_summary, invalid_samples, sample_warnings = summarize_samples(
            sample_lines
        )

    sample_identity_changed = bool(
        sample_summary and sample_summary.get("identity_changed") is True
    )
    identity_changed = manifest_window.identity_changed or sample_identity_changed
    warnings.extend(logcat.warnings)
    warnings.extend(sample_warnings)
    if manifest_window.identity_changed:
        warnings.append(
            "Manifest reports identity_changed=true; cross-process FPS and "
            "frame-timing aggregates were suppressed."
        )

    frame_metrics_suppressed_reason: str | None = None
    if invalid_manifest_window:
        fps_summary: dict[str, object] | None = None
        frame_summary: dict[str, object] | None = None
        frame_metrics_suppressed_reason = "invalid_manifest_window"
    elif identity_changed:
        fps_summary = None
        frame_summary = None
        frame_metrics_suppressed_reason = "identity_changed"
    else:
        fps_summary = summarize_fps(logcat.fps_records)
        frame_summary = summarize_frame_timing(logcat.frame_timing_records)

    if (
        frame_summary is not None
        and frame_summary.get("poll_fences", {}).get("mixed_mode") is True
    ):
        warnings.append(
            "frame-timing window mixes poll_fences=0 and poll_fences=1; "
            "pure-mode A/B conclusions are not allowed."
        )
    if (
        frame_summary is not None
        and frame_summary.get("cache_modes", {}).get("mixed_mode") is True
    ):
        warnings.append(
            "frame-timing window mixes cache_mode values; pure cache-mode "
            "A/B conclusions are not allowed."
        )

    cache_metrics_suppressed_reason: str | None = None
    cache_summary: dict[str, object] | None
    if invalid_manifest_window:
        cache_summary = None
        cache_metrics_suppressed_reason = "invalid_manifest_window"
    elif identity_changed:
        cache_summary = None
        cache_metrics_suppressed_reason = "identity_changed"
    elif not manifest_window.valid:
        cache_summary = _unavailable_cache_scan(
            "valid manifest with PID and monotonic window required"
        )
        cache_metrics_suppressed_reason = "manifest_required"
    elif manifest_window.pid is None:
        cache_summary = _unavailable_cache_scan(
            "manifest.start_pid is required for cache-scan PID filtering"
        )
        cache_metrics_suppressed_reason = "manifest_pid_required"
    else:
        cache_summary = summarize_cache_scan(logcat)
        point_count = int(cache_summary["point_samples"]["count"])
        if point_count:
            warnings.append(
                "cache-scan point samples are audit-biased every-256-round "
                "observations; they are not used as batch estimates."
            )
        if cache_summary["cache_modes"]["mixed_mode"]:
            warnings.append(
                "cache-scan window mixes cache_mode values; cross-mode batch "
                "totals are omitted and pure cache-mode A/B conclusions are not allowed."
            )
        exclusions = cache_summary["batch_exclusions"]
        if exclusions:
            warnings.append(
                "Some cache-scan batch records were excluded: "
                + json.dumps(exclusions, sort_keys=True)
            )

    return {
        "parsed_record_total": (
            len(logcat.fps_records)
            + len(logcat.frame_timing_records)
            + (int(sample_summary["count"]) if sample_summary else 0)
        ),
        "parsed_records": {
            "fps": len(logcat.fps_records),
            "frame_timing": len(logcat.frame_timing_records),
            "samples": int(sample_summary["count"]) if sample_summary else 0,
        },
        "invalid_records": {
            "fps": logcat.invalid_fps,
            "frame_timing": logcat.invalid_frame_timing,
            "timestamps": logcat.invalid_timestamps,
            "samples": invalid_samples,
        },
        "logcat_filter": {
            "bounded_window_applied": not invalid_manifest_window
            and manifest_window.valid,
            "excluded_before_window": logcat.excluded_before_window,
            "excluded_after_window": logcat.excluded_after_window,
            "excluded_cross_window_start": logcat.excluded_cross_window_start,
        },
        "logcat_scope": logcat_scope,
        "identity_changed": identity_changed,
        "frame_metrics_suppressed_reason": frame_metrics_suppressed_reason,
        "cache_metrics_suppressed_reason": cache_metrics_suppressed_reason,
        "fps": fps_summary,
        "frame_timing": frame_summary,
        "cache_scan": cache_summary,
        "samples": sample_summary,
        "warnings": warnings,
    }

def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize an offline Android runtime logcat and optional JSONL samples."
    )
    parser.add_argument(
        "--logcat",
        required=True,
        type=Path,
        help="UTF-8 logcat text file",
    )
    parser.add_argument(
        "--samples",
        type=Path,
        help="optional UTF-8 JSONL telemetry samples",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="optional capture manifest.json used to bound logcat by monotonic time",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="destination JSON file",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        logcat_text = args.logcat.read_text(encoding="utf-8")
        sample_lines = None
        if args.samples is not None:
            sample_lines = args.samples.read_text(encoding="utf-8").splitlines()
        manifest = None
        if args.manifest is not None:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = summarize_android_runtime(logcat_text, sample_lines, manifest)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        parser.error(str(error))

    return 2 if result["logcat_scope"]["mode"] == "invalid_manifest_window" else 0


if __name__ == "__main__":
    raise SystemExit(main())
