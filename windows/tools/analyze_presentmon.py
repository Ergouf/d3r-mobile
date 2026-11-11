#!/usr/bin/env python3
"""Summarize PresentMon 2.6 CSVs without modifying the captures.

Each file has its own window, relative to its first finite
CPUStartQPCTimeInMs value. The start is inclusive and the end exclusive.
Percentiles use linear interpolation; thresholds are strict greater-than.
"""

import argparse
import collections
import csv
import json
import math
from pathlib import Path
import sys


GROUP_FIELDS = ("ProcessID", "SwapChainAddress", "VidPnSourceId", "LayerIndex", "PresentMode")
METRICS = ("MsBetweenPresents", "MsBetweenDisplayChange", "MsGPUBusy", "MsGPUTime", "MsUntilDisplayed")
AVAILABILITY_FIELDS = (*METRICS, "MsInPresentAPI", "CPUStartQPCTimeInMs")
THRESHOLDS = (25.0, 33.33, 50.0)
BIN_CENTERS = (8.33, 16.67, 25.0, 33.33)
BIN_TOLERANCE_MS = 0.5


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def rounded(value):
    return round(value, 4) if value is not None else None


def percentile(values, fraction):
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def metric_summary(values):
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "p99": None, "max": None,
                "above_ms": {format(limit, "g"): {"n": 0, "ratio": None} for limit in THRESHOLDS},
                "near_ms": {format(center, "g"): {"n": 0, "ratio": None} for center in BIN_CENTERS}}
    values = sorted(values)
    count = len(values)
    above = {format(limit, "g"): sum(value > limit for value in values) for limit in THRESHOLDS}
    bins = {format(center, "g"): sum(abs(value - center) <= BIN_TOLERANCE_MS for value in values)
            for center in BIN_CENTERS}
    return {"n": count, "mean": rounded(math.fsum(values) / count),
            "p50": rounded(percentile(values, .5)), "p95": rounded(percentile(values, .95)),
            "p99": rounded(percentile(values, .99)), "max": rounded(values[-1]),
            "above_ms": {key: {"n": value, "ratio": rounded(value / count)} for key, value in above.items()},
            "near_ms": {key: {"n": value, "ratio": rounded(value / count)} for key, value in bins.items()}}


def group_value(field, value):
    if not value:
        return None
    if field in ("ProcessID", "VidPnSourceId", "LayerIndex"):
        try:
            return int(value)
        except ValueError:
            pass
    return value


def analyze(path, skip_seconds, duration_seconds):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if not fields:
            raise ValueError(f"{path}: missing CSV header")
        if "ProcessID" not in fields:
            raise ValueError(f"{path}: missing ProcessID column")
        rows = list(reader)

    first_time = next((number(row.get("CPUStartQPCTimeInMs")) for row in rows
                       if number(row.get("CPUStartQPCTimeInMs")) is not None), None)
    window_requested = skip_seconds != 0 or duration_seconds is not None
    if window_requested and first_time is None:
        raise ValueError(f"{path}: time window requires a finite CPUStartQPCTimeInMs")
    start = first_time + skip_seconds * 1000 if first_time is not None else None
    end = start + duration_seconds * 1000 if duration_seconds is not None else None
    groups = {}
    selected = missing_time = 0
    for row in rows:
        time = number(row.get("CPUStartQPCTimeInMs"))
        if window_requested:
            if time is None:
                missing_time += 1
                continue
            if time < start or (end is not None and time >= end):
                continue
        selected += 1
        key = tuple(group_value(field, row.get(field)) for field in GROUP_FIELDS)
        if key not in groups:
            groups[key] = {"rows": 0, "values": {field: [] for field in AVAILABILITY_FIELDS},
                           "runtimes": collections.Counter()}
        group = groups[key]
        group["rows"] += 1
        group["runtimes"][row.get("PresentRuntime") or "<missing>"] += 1
        for field in AVAILABILITY_FIELDS:
            value = number(row.get(field))
            if value is not None:
                group["values"][field].append(value)

    summaries = []
    for key, group in sorted(groups.items(), key=lambda item: tuple(str(value) for value in item[0])):
        count = group["rows"]
        availability = {}
        for field in AVAILABILITY_FIELDS:
            values = group["values"][field]
            availability[field] = {"column_present": field in fields, "n": len(values),
                                   "na_n": count - len(values), "na_ratio": rounded(1 - len(values) / count),
                                   "nonzero_n": sum(value != 0 for value in values),
                                   "min": rounded(min(values)) if values else None,
                                   "max": rounded(max(values)) if values else None}
        summaries.append({"key": dict(zip(GROUP_FIELDS, key)), "rows": count,
                          "present_runtime_counts": dict(group["runtimes"]), "availability": availability,
                          "metrics": {field: metric_summary(group["values"][field]) for field in METRICS}})
    return {"file": str(path), "rows_read": len(rows), "rows_selected": selected,
            "rows_excluded_missing_window_time": missing_time,
            "window": {"origin_cpu_start_qpc_ms": first_time, "skip_seconds": skip_seconds,
                       "duration_seconds": duration_seconds, "start_cpu_start_qpc_ms": start,
                       "end_cpu_start_qpc_ms_exclusive": end},
            "group_columns_present": {field: field in fields for field in GROUP_FIELDS}, "groups": summaries}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csvs", nargs="+", type=Path)
    parser.add_argument("--skip-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float)
    args = parser.parse_args(argv)
    if not math.isfinite(args.skip_seconds) or args.skip_seconds < 0:
        parser.error("--skip-seconds must be finite and nonnegative")
    if args.duration_seconds is not None and (not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0):
        parser.error("--duration-seconds must be finite and positive")
    try:
        files = [analyze(path, args.skip_seconds, args.duration_seconds) for path in args.csvs]
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        parser.error(str(error))
    json.dump({"schema": "presentmon-2.6-summary-v1", "group_fields": GROUP_FIELDS,
               "threshold_comparison": ">", "threshold_ratio_denominator": "finite metric values",
               "near_bin_tolerance_ms": BIN_TOLERANCE_MS, "files": files}, sys.stdout,
              ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
