from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "summarize_android_runtime.py"
)
SPEC = importlib.util.spec_from_file_location("summarize_android_runtime", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)


def cache_scan_line(
    timestamp_s: float,
    pid: int,
    *,
    pages: int = 100,
    changed: int = 1,
    us: int = 10,
    generation: int = 1,
    write_faults: int = 0,
    watch_misses: int = 0,
    batch: dict[str, int] | None = None,
    cache_mode: int | None = None,
) -> str:
    line = (
        f"{timestamp_s:.9f} {pid} 637 I d3gpu : cache-scan: "
        f"pages={pages} changed={changed} us={us} generation={generation} "
        f"write-faults={write_faults} watch-misses={watch_misses}"
    )
    if batch is not None:
        line += " " + " ".join(f"{key}={value}" for key, value in batch.items())
    if cache_mode is not None:
        line += f" cache_mode={cache_mode}"
    return line


class SummarizeRuntimeTests(unittest.TestCase):
    def test_net_battery_current_is_reported_without_fabricating_usb_power(self) -> None:
        samples = [json.dumps({
            "timestamp_s": timestamp,
            "battery": {"charge_counter_uah": 1000000, "temperature_deci_c": 310,
                        "usb_powered": True, "external_powered": True,
                        "current_now_ua": current},
        }) for timestamp, current in ((0, -114000), (2, -225000), (4, None))]
        result = runtime.summarize_android_runtime("", samples)["samples"]
        current = result["battery_net_current_ua"]
        self.assertEqual(current["count"], 2)
        self.assertEqual(current["min"], -225000)
        self.assertEqual(current["max"], -114000)
        self.assertEqual(current["sample_mean"], -169500)
        self.assertIsNone(result["average_discharge_ma"])
        self.assertEqual(result["average_discharge_status"], "charging")

    def test_missing_current_stays_unavailable(self) -> None:
        samples = [json.dumps({"timestamp_s": 0, "battery": {
            "charge_counter_uah": 1000000, "temperature_deci_c": 310,
            "usb_powered": False, "current_now_ua": "unsupported",
        }})]
        result = runtime.summarize_android_runtime("", samples)["samples"]
        self.assertEqual(result["battery_net_current_ua"]["count"], 0)
        self.assertIsNone(result["battery_net_current_ua"]["sample_mean"])

    def test_fps_weighting_and_nearest_rank_frame_statistics(self) -> None:
        logcat = "\n".join(
            [
                "11-10 10:00:00.000 D/d3gpu: game frames=100 fps=30 interval=1.000s",
                "11-10 10:00:03.000 D/d3gpu: game frames=200 fps=50 interval=3.000s",
                "frame-timing frame=100 cpu_us=10 gpu_wait_us=20 present_us=30 total_us=100",
                "frame-timing frame=101 cpu_us=10 gpu_wait_us=20 present_us=30 total_us=17000",
                "frame-timing frame=102 cpu_us=10 gpu_wait_us=20 present_us=30 total_us=33400",
                "frame-timing frame=103 cpu_us=10 gpu_wait_us=20 present_us=30 total_us=40000",
            ]
        )

        result = runtime.summarize_android_runtime(logcat)

        self.assertEqual(result["parsed_records"]["fps"], 2)
        self.assertEqual(result["parsed_records"]["frame_timing"], 4)
        self.assertEqual(result["fps"]["min"], 30.0)
        self.assertEqual(result["fps"]["median"], 40.0)
        self.assertEqual(result["fps"]["max"], 50.0)
        self.assertAlmostEqual(result["fps"]["interval_weighted_mean"], 45.0)
        self.assertEqual(result["frame_timing"]["p50_us"], 17000)
        self.assertEqual(result["frame_timing"]["p95_us"], 40000)
        self.assertEqual(result["frame_timing"]["p99_us"], 40000)
        self.assertEqual(result["frame_timing"]["over_16_667_ms"], 3)
        self.assertEqual(result["frame_timing"]["over_33_334_ms"], 2)
        self.assertEqual(
            result["frame_timing"]["metric"], "present_callback_wall"
        )
        self.assertEqual(result["frame_timing"]["source_field"], "total_us")
        self.assertFalse(
            result["frame_timing"]["supports_native_composite_rate_analysis"]
        )
        self.assertFalse(result["frame_timing"]["can_assert_60_fps"])
        self.assertEqual(
            result["frame_timing"]["components_us"]["fence_wait_us"][
                "missing_count"
            ],
            4,
        )
        self.assertEqual(
            result["frame_timing"]["poll_fences"]["missing_count"], 4
        )
        self.assertFalse(
            result["frame_timing"]["poll_fences"]["pure_mode_analysis_allowed"]
        )
        self.assertEqual(runtime.nearest_rank([100, 200, 300, 400], 50), 200)

    def test_bounded_component_stats_and_mixed_poll_fence_mode(self) -> None:
        logcat = "\n".join(
            [
                "[ 100.005] I/d3gpu: frame-timing frame=0 cpu_us=999999 "
                "gpu_wait_us=999999 present_us=999999 total_us=999999 "
                "fence_wait_us=999999 poll_fences=1 frame_interval_us=10000",
                "[ 101.000] I/d3gpu: frame-timing frame=1 cpu_us=100 "
                "gpu_wait_us=200 present_us=300 total_us=600 "
                "fence_wait_us=50 poll_fences=0 frame_interval_us=10000",
                "[ 102.000] I/d3gpu: frame-timing frame=2 cpu_us=200 "
                "gpu_wait_us=400 present_us=600 total_us=1200 "
                "fence_wait_us=150 poll_fences=1 frame_interval_us=10000",
                "[ 103.000] I/d3gpu: frame-timing frame=3 cpu_us=300 "
                "gpu_wait_us=600 present_us=900 total_us=1800 "
                "fence_wait_us=250 poll_fences=0 frame_interval_us=10000",
                "[ 104.000] I/d3gpu: frame-timing frame=4 cpu_us=400 "
                "gpu_wait_us=800 present_us=1200 total_us=2400 "
                "fence_wait_us=350 poll_fences=1 frame_interval_us=10000",
            ]
        )
        manifest = {
            "status": "complete",
            "identity_changed": False,
            "logcat_window": {
                "device_monotonic_start_s": 100,
                "device_monotonic_end_s": 105,
            },
        }

        result = runtime.summarize_android_runtime(logcat, manifest=manifest)

        timing = result["frame_timing"]
        self.assertEqual(timing["count"], 4)
        self.assertTrue(timing["components_are_not_additive"])
        self.assertTrue(
            timing["field_notes"]["timing_components_are_not_additive"]
        )
        self.assertFalse(timing["can_assert_60_fps"])
        expected = {
            "cpu_us": (250.0, 200.0, 400.0),
            "gpu_wait_us": (500.0, 400.0, 800.0),
            "present_us": (750.0, 600.0, 1200.0),
            "total_us": (1500.0, 1200.0, 2400.0),
            "fence_wait_us": (200.0, 150.0, 350.0),
        }
        for field_name, (mean_us, p50_us, max_us) in expected.items():
            component = timing["components_us"][field_name]
            self.assertEqual(component["count"], 4)
            self.assertEqual(component["missing_count"], 0)
            self.assertEqual(component["mean_us"], mean_us)
            self.assertEqual(component["p50_us"], p50_us)
            self.assertEqual(component["p95_us"], max_us)
            self.assertEqual(component["p99_us"], max_us)
            self.assertEqual(component["max_us"], max_us)
        self.assertEqual(
            timing["poll_fences"]["counts_by_value"],
            {"0": 2, "1": 2, "missing": 0},
        )
        self.assertTrue(timing["poll_fences"]["mixed_mode"])
        self.assertFalse(
            timing["poll_fences"]["pure_mode_analysis_allowed"]
        )
        self.assertTrue(
            any("mixes poll_fences" in warning for warning in result["warnings"])
        )

    def test_cache_scan_batch_aggregation_and_exclusions(self) -> None:
        logcat = "\n".join(
            [
                cache_scan_line(
                    101.0,
                    123,
                    pages=200,
                    changed=2,
                    us=12000,
                    batch={
                        "batch_count": 100,
                        "batch_total_us": 10000,
                        "batch_max_us": 150,
                        "batch_begin_us": 101_000_000,
                        "batch_pages": 1000,
                        "batch_changed": 20,
                    },
                ),
                cache_scan_line(
                    102.0,
                    123,
                    pages=300,
                    changed=3,
                    us=13000,
                    batch={
                        "batch_count": 300,
                        "batch_total_us": 45000,
                        "batch_max_us": 200,
                        "batch_begin_us": 102_000_000,
                        "batch_pages": 3600,
                        "batch_changed": 120,
                    },
                ),
                cache_scan_line(103.0, 123),
                cache_scan_line(
                    104.0,
                    123,
                    batch={
                        "batch_count": 256,
                        "batch_total_us": 1000,
                        "batch_max_us": 100,
                        "batch_begin_us": 99_999_000,
                        "batch_pages": 100,
                        "batch_changed": 1,
                    },
                ),
                cache_scan_line(
                    105.0,
                    999,
                    batch={
                        "batch_count": 256,
                        "batch_total_us": 999999,
                        "batch_max_us": 999,
                        "batch_begin_us": 105_000_000,
                        "batch_pages": 999,
                        "batch_changed": 999,
                    },
                ),
                cache_scan_line(
                    106.0,
                    123,
                    batch={
                        "batch_count": 0,
                        "batch_total_us": 1,
                        "batch_max_us": 1,
                        "batch_begin_us": 106_000_000,
                        "batch_pages": 1,
                        "batch_changed": 1,
                    },
                ),
                cache_scan_line(
                    107.0,
                    123,
                    batch={
                        "batch_count": 10,
                        "batch_total_us": 100,
                        "batch_max_us": 10,
                        "batch_begin_us": 108_000_000,
                        "batch_pages": 10,
                        "batch_changed": 1,
                    },
                ),
                cache_scan_line(121.0, 123),
            ]
        )
        manifest = {
            "status": "complete",
            "identity_changed": False,
            "start_pid": 123,
            "logcat_window": {
                "device_monotonic_start_s": 100,
                "device_monotonic_end_s": 110,
            },
        }

        result = runtime.summarize_android_runtime(logcat, manifest=manifest)

        cache = result["cache_scan"]
        self.assertTrue(cache["available"])
        self.assertEqual(cache["point_samples"]["count"], 6)
        self.assertEqual(cache["filter_counts"]["excluded_pid"], 1)
        self.assertEqual(cache["filter_counts"]["excluded_after_window"], 1)
        batches = cache["batches"]
        self.assertEqual(batches["batch_record_count"], 2)
        self.assertFalse(batches["pure_mode_analysis_allowed"])
        self.assertTrue(batches["cross_mode_total_omitted"])
        self.assertEqual(
            batches["aggregate_omitted_reason"],
            "missing_or_unconfirmed_cache_mode",
        )
        self.assertIsNone(batches["total_scan_count"])
        missing_group = batches["by_cache_mode"]["missing"]
        self.assertEqual(missing_group["total_scan_count"], 400)
        self.assertEqual(missing_group["total_us"], 55000)
        self.assertEqual(missing_group["weighted_mean_us"], 137.5)
        self.assertEqual(missing_group["max_us"], 200)
        self.assertEqual(missing_group["pages_per_scan_mean"], 11.5)
        self.assertEqual(missing_group["changed_per_scan_mean"], 0.35)
        self.assertNotIn("p99", missing_group)
        exclusions = cache["batch_exclusions"]
        self.assertEqual(exclusions["missing_batch_fields"], 1)
        self.assertEqual(exclusions["batch_starts_before_window"], 1)
        self.assertEqual(exclusions["invalid_batch_count"], 1)
        self.assertEqual(exclusions["batch_begins_after_log_line"], 1)
        self.assertIn("audit-biased", cache["point_samples"]["audit_bias_warning"])

    def test_cache_mode_counts_and_mixed_batch_grouping(self) -> None:
        frame_lines = []
        cache_lines = []
        batch_values = (
            (0, 100, 1000),
            (1, 200, 5000),
            (2, 300, 12000),
            (None, 400, 20000),
        )
        for index, (mode, count, total_us) in enumerate(batch_values, start=1):
            suffix = f" cache_mode={mode}" if mode is not None else ""
            frame_lines.append(
                f"{100 + index:.6f} 123 1607 I d3gpu : frame-timing "
                f"frame={index} cpu_us={index * 10} gpu_wait_us={index * 20} "
                f"present_us={index * 30} total_us={index * 100} "
                f"frame_interval_us=25000 poll_fences=0{suffix}"
            )
            cache_lines.append(
                cache_scan_line(
                    100 + index,
                    123,
                    batch={
                        "batch_count": count,
                        "batch_total_us": total_us,
                        "batch_max_us": 100,
                        "batch_begin_us": (100 + index) * 1_000_000,
                        "batch_pages": 1000,
                        "batch_changed": 10,
                    },
                    cache_mode=mode,
                )
            )
        manifest = {
            "status": "complete",
            "identity_changed": False,
            "start_pid": 123,
            "logcat_window": {
                "device_monotonic_start_s": 100,
                "device_monotonic_end_s": 110,
            },
        }

        result = runtime.summarize_android_runtime(
            "\n".join(frame_lines + cache_lines), manifest=manifest
        )

        expected_counts = {"0": 1, "1": 1, "2": 1, "missing": 1}
        frame_modes = result["frame_timing"]["cache_modes"]
        self.assertEqual(frame_modes["counts_by_value"], expected_counts)
        self.assertTrue(frame_modes["mixed_mode"])
        self.assertFalse(frame_modes["pure_mode_analysis_allowed"])
        cache = result["cache_scan"]
        self.assertEqual(cache["cache_modes"]["counts_by_value"], expected_counts)
        self.assertTrue(cache["cache_modes"]["mixed_mode"])
        self.assertFalse(cache["cache_modes"]["pure_mode_analysis_allowed"])
        batches = cache["batches"]
        self.assertTrue(batches["mixed_mode"])
        self.assertFalse(batches["pure_mode_analysis_allowed"])
        self.assertTrue(batches["cross_mode_total_omitted"])
        self.assertEqual(
            batches["aggregate_omitted_reason"], "mixed_cache_mode"
        )
        self.assertIsNone(batches["total_scan_count"])
        self.assertIsNone(batches["weighted_mean_us"])
        self.assertEqual(batches["by_cache_mode"]["0"]["total_scan_count"], 100)
        self.assertEqual(batches["by_cache_mode"]["1"]["total_scan_count"], 200)
        self.assertEqual(batches["by_cache_mode"]["2"]["total_scan_count"], 300)
        self.assertEqual(
            batches["by_cache_mode"]["missing"]["total_scan_count"], 400
        )

    def test_native_composite_interval_is_preferred_over_total_us(self) -> None:
        logcat = "\n".join(
            [
                "frame-timing frame=1 cpu_us=10 gpu_wait_us=20 present_us=30 "
                "total_us=40000 frame_interval_us=1000",
                "frame-timing frame=2 cpu_us=10 gpu_wait_us=20 present_us=30 "
                "total_us=100 frame_interval_us=17000",
            ]
        )

        result = runtime.summarize_android_runtime(logcat)

        timing = result["frame_timing"]
        self.assertEqual(timing["metric"], "native_composite_interval")
        self.assertEqual(timing["source_field"], "frame_interval_us")
        self.assertEqual(timing["p50_us"], 1000)
        self.assertEqual(timing["p95_us"], 17000)
        self.assertEqual(timing["over_16_667_ms"], 1)
        self.assertEqual(timing["records_without_frame_interval"], 0)
        self.assertTrue(timing["supports_native_composite_rate_analysis"])
        self.assertFalse(timing["can_assert_60_fps"])
        self.assertIn("does not establish", timing["metric_note"])
        self.assertTrue(timing["field_notes"]["timing_components_are_not_additive"])

    def test_malformed_and_unrelated_log_lines_are_not_misparsed(self) -> None:
        logcat = "\n".join(
            [
                "notd3gpu: game frames=999 fps=1 interval=1s",
                "not-frame-timing frame=6 cpu_us=1 gpu_wait_us=2 present_us=3 total_us=40",
                "D/d3gpu: game frames=12 fps=oops interval=1.000s",
                "frame-timing frame=7 cpu_us=1 gpu_wait_us=2",
                "frame-timing frame=8 cpu_us=1 gpu_wait_us=2 present_us=3 total_us=50",
            ]
        )

        result = runtime.summarize_android_runtime(logcat)

        self.assertEqual(result["parsed_records"]["fps"], 0)
        self.assertEqual(result["parsed_records"]["frame_timing"], 1)
        self.assertEqual(result["invalid_records"]["fps"], 1)
        self.assertEqual(result["invalid_records"]["frame_timing"], 1)
        self.assertEqual(result["frame_timing"]["count"], 1)
        self.assertEqual(result["frame_timing"]["p50_us"], 50)

    def test_monotonic_prefix_parsing_is_strict(self) -> None:
        self.assertEqual(
            runtime.parse_monotonic_timestamp(
                "[ 1234.567] I/d3gpu: game frames=1 fps=60 interval=1s"
            ),
            1234.567,
        )
        self.assertEqual(
            runtime.parse_monotonic_timestamp(
                "1234.568 100 101 I d3gpu: frame-timing frame=1"
            ),
            1234.568,
        )
        self.assertIsNone(
            runtime.parse_monotonic_timestamp(
                "11-10 10:00:00.000 D/d3gpu: game frames=1 fps=60 interval=1s"
            )
        )

    def test_manifest_window_filters_crossing_and_outside_records(self) -> None:
        logcat = "\n".join(
            [
                "[ 99.000] I/d3gpu: game frames=1 fps=20 interval=2.000s",
                "[ 100.500] I/d3gpu: game frames=2 fps=30 interval=1.000s",
                "100.500 10 11 I d3gpu: game frames=3 fps=40 interval=0.500s",
                "[ 110.000] I/d3gpu: game frames=4 fps=50 interval=2.000s",
                "[ 110.001] I/d3gpu: game frames=5 fps=60 interval=1.000s",
                "[ 100.010] I/d3gpu: frame-timing frame=1 cpu_us=1 "
                "gpu_wait_us=2 present_us=3 total_us=100 frame_interval_us=20000",
                "[ 100.020] I/d3gpu: frame-timing frame=2 cpu_us=1 "
                "gpu_wait_us=2 present_us=3 total_us=100 frame_interval_us=10000",
                "110.000 10 11 I d3gpu: frame-timing frame=3 cpu_us=1 "
                "gpu_wait_us=2 present_us=3 total_us=100 frame_interval_us=10000",
                "[ 110.001] I/d3gpu: frame-timing frame=4 cpu_us=1 "
                "gpu_wait_us=2 present_us=3 total_us=100 frame_interval_us=10000",
                "11-10 10:00:00.000 D/d3gpu: frame-timing frame=5 "
                "cpu_us=1 gpu_wait_us=2 present_us=3 total_us=100",
            ]
        )
        manifest = {
            "status": "complete",
            "identity_changed": False,
            "logcat_window": {
                "device_monotonic_start_s": 100,
                "device_monotonic_end_s": 110,
                "boot_id": "boot-1",
            },
        }

        result = runtime.summarize_android_runtime(logcat, manifest=manifest)

        self.assertEqual(result["logcat_scope"]["mode"], "manifest_bounded")
        self.assertTrue(result["logcat_scope"]["is_current_capture"])
        self.assertEqual(result["parsed_records"]["fps"], 2)
        self.assertEqual(result["parsed_records"]["frame_timing"], 2)
        self.assertEqual(result["fps"]["median"], 45.0)
        self.assertEqual(result["frame_timing"]["p50_us"], 10000)
        self.assertEqual(result["invalid_records"]["timestamps"], 1)
        self.assertEqual(result["logcat_filter"]["excluded_before_window"], 1)
        self.assertEqual(result["logcat_filter"]["excluded_after_window"], 2)
        self.assertEqual(result["logcat_filter"]["excluded_cross_window_start"], 2)

    def test_invalid_manifest_window_refuses_full_history(self) -> None:
        logcat = (
            "[ 100.000] I/d3gpu: game frames=1 fps=60 interval=1.000s"
        )
        manifest = {
            "status": "complete",
            "logcat_window": {
                "device_monotonic_start_s": 100,
                "device_monotonic_end_s": None,
            },
        }

        result = runtime.summarize_android_runtime(logcat, manifest=manifest)

        self.assertEqual(
            result["logcat_scope"]["mode"], "invalid_manifest_window"
        )
        self.assertEqual(result["parsed_records"]["fps"], 0)
        self.assertIsNone(result["fps"])
        self.assertIsNone(result["frame_timing"])
        self.assertEqual(
            result["frame_metrics_suppressed_reason"], "invalid_manifest_window"
        )
        self.assertTrue(
            any("full-history" in warning for warning in result["warnings"])
        )

    def test_manifest_identity_and_incomplete_status_are_enforced(self) -> None:
        logcat = (
            "[ 101.000] I/d3gpu: game frames=1 fps=60 interval=1.000s\n"
            "[ 101.010] I/d3gpu: frame-timing frame=1 cpu_us=1 "
            "gpu_wait_us=2 present_us=3 total_us=100 frame_interval_us=10000"
        )
        samples = [
            json.dumps(
                {
                    "timestamp_s": 0,
                    "battery": {
                        "charge_counter_uah": 1000,
                        "temperature_deci_c": 300,
                        "usb_powered": False,
                        "external_powered": False,
                    },
                    "identity": {
                        "pid": 100,
                        "start_ticks": "1000",
                        "apk_sha256": "aaa",
                    },
                }
            )
        ]
        manifest = {
            "status": "incomplete",
            "identity_changed": True,
            "logcat_window": {
                "device_monotonic_start_s": 100,
                "device_monotonic_end_s": 102,
                "boot_id": "boot-1",
            },
        }

        result = runtime.summarize_android_runtime(logcat, samples, manifest)

        self.assertTrue(result["identity_changed"])
        self.assertEqual(
            result["frame_metrics_suppressed_reason"], "identity_changed"
        )
        self.assertIsNone(result["fps"])
        self.assertIsNone(result["frame_timing"])
        self.assertFalse(result["logcat_scope"]["capture_complete"])
        self.assertEqual(result["logcat_scope"]["capture_status"], "incomplete")
        self.assertTrue(
            any("incomplete" in warning for warning in result["warnings"])
        )

    def test_cli_accepts_manifest_without_adb(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            logcat_path = base / "logcat.txt"
            manifest_path = base / "manifest.json"
            output_path = base / "summary.json"
            logcat_path.write_text(
                "[ 100.500] I/d3gpu: game frames=1 fps=60 interval=0.500s\n",
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "identity_changed": False,
                        "logcat_window": {
                            "device_monotonic_start_s": 100,
                            "device_monotonic_end_s": 101,
                        },
                    }
                ),
                encoding="utf-8",
            )

            exit_code = runtime.main(
                [
                    "--logcat",
                    str(logcat_path),
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["logcat_scope"]["mode"], "manifest_bounded")
            self.assertEqual(result["fps"]["max"], 60.0)

    def test_charging_suppresses_discharge_rate(self) -> None:
        samples = [
            json.dumps(
                {
                    "timestamp_s": 0,
                    "battery": {
                        "charge_counter_uah": 1_000_000,
                        "temperature_deci_c": 300,
                        "usb_powered": False,
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 1800,
                    "battery": {
                        "charge_counter_uah": 1_020_000,
                        "temperature_deci_c": 410,
                        "usb_powered": True,
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 3600,
                    "battery": {
                        "charge_counter_uah": 1_050_000,
                        "temperature_deci_c": 390,
                        "usb_powered": False,
                    },
                }
            ),
        ]

        result = runtime.summarize_android_runtime("", samples)

        self.assertIsNone(result["samples"]["average_discharge_ma"])
        self.assertEqual(result["samples"]["average_discharge_status"], "charging")
        self.assertEqual(result["samples"]["temperature_deci_c"]["min"], 300.0)
        self.assertEqual(result["samples"]["temperature_deci_c"]["max"], 410.0)
        self.assertEqual(result["samples"]["charge_counter_uah"]["change_uah"], 50_000)
        self.assertAlmostEqual(result["samples"]["duration_s"], 3600.0)

    def test_external_powered_prevents_false_discharge_rate(self) -> None:
        samples = [
            json.dumps(
                {
                    "timestamp_s": 0,
                    "battery": {
                        "charge_counter_uah": 1_000_000,
                        "temperature_deci_c": 300,
                        "usb_powered": False,
                        "external_powered": True,
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 1800,
                    "battery": {
                        "charge_counter_uah": 1_100_000,
                        "temperature_deci_c": 310,
                        "usb_powered": False,
                        "external_powered": True,
                    },
                }
            ),
        ]

        result = runtime.summarize_android_runtime("", samples)

        self.assertIsNone(result["samples"]["average_discharge_ma"])
        self.assertEqual(result["samples"]["average_discharge_status"], "charging")
        self.assertEqual(result["samples"]["external_power"]["powered_count"], 2)

    def test_ac_power_is_combined_when_external_flag_is_absent(self) -> None:
        samples = [
            json.dumps(
                {
                    "timestamp_s": 0,
                    "battery": {
                        "charge_counter_uah": 1_000_000,
                        "temperature_deci_c": 300,
                        "usb_powered": False,
                        "ac_powered": True,
                        "wireless_powered": False,
                        "dock_powered": False,
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 1800,
                    "battery": {
                        "charge_counter_uah": 1_050_000,
                        "temperature_deci_c": 310,
                        "usb_powered": False,
                        "ac_powered": True,
                        "wireless_powered": False,
                        "dock_powered": False,
                    },
                }
            ),
        ]

        result = runtime.summarize_android_runtime("", samples)

        self.assertIsNone(result["samples"]["average_discharge_ma"])
        self.assertEqual(result["samples"]["average_discharge_status"], "charging")

    def test_all_unplugged_samples_compute_discharge_rate(self) -> None:
        samples = [
            json.dumps(
                {
                    "timestamp_s": 10,
                    "battery": {
                        "charge_counter_uah": 1_000_000,
                        "temperature_deci_c": 350,
                        "usb_powered": False,
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 1810,
                    "battery": {
                        "charge_counter_uah": 820_000,
                        "temperature_deci_c": 360,
                        "usb_powered": False,
                    },
                }
            ),
        ]

        result = runtime.summarize_android_runtime("", samples)

        self.assertEqual(result["samples"]["average_discharge_status"], "ok")
        self.assertAlmostEqual(result["samples"]["average_discharge_ma"], 360.0)

    def test_empty_inputs_have_explicit_null_metrics(self) -> None:
        result = runtime.summarize_android_runtime("", None)

        self.assertEqual(result["parsed_record_total"], 0)
        self.assertIsNone(result["fps"]["min"])
        self.assertIsNone(result["fps"]["median"])
        self.assertIsNone(result["fps"]["max"])
        self.assertIsNone(result["fps"]["interval_weighted_mean"])
        self.assertIsNone(result["frame_timing"]["p50_us"])
        self.assertIsNone(result["frame_timing"]["max_us"])
        self.assertIsNone(result["samples"])
        self.assertFalse(result["identity_changed"])
        self.assertEqual(result["logcat_scope"]["mode"], "unbounded_history")
        self.assertFalse(result["logcat_scope"]["is_current_capture"])
        self.assertTrue(
            any("unbounded-history" in warning for warning in result["warnings"])
        )

    def test_identity_change_omits_cross_process_frame_totals(self) -> None:
        logcat = (
            "frame-timing frame=1 cpu_us=10 gpu_wait_us=20 "
            "present_us=30 total_us=60\n"
            + cache_scan_line(
                101.0,
                100,
                batch={
                    "batch_count": 256,
                    "batch_total_us": 1000,
                    "batch_max_us": 10,
                    "batch_begin_us": 101_000_000,
                    "batch_pages": 100,
                    "batch_changed": 1,
                },
            )
        )
        samples = [
            json.dumps(
                {
                    "timestamp_s": 0,
                    "battery": {
                        "charge_counter_uah": 1000,
                        "temperature_deci_c": 300,
                        "usb_powered": False,
                    },
                    "identity": {
                        "pid": 100,
                        "start_ticks": "1000",
                        "apk_sha256": "aaa",
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 60,
                    "battery": {
                        "charge_counter_uah": 900,
                        "temperature_deci_c": 310,
                        "usb_powered": False,
                    },
                    "identity": {
                        "pid": 200,
                        "start_ticks": "2000",
                        "apk_sha256": "bbb",
                    },
                }
            ),
        ]

        result = runtime.summarize_android_runtime(logcat, samples)

        self.assertTrue(result["identity_changed"])
        self.assertEqual(
            result["samples"]["identity_changed_fields"],
            ["pid", "start_ticks", "apk_sha256"],
        )
        self.assertIsNone(result["fps"])
        self.assertIsNone(result["frame_timing"])
        self.assertIsNone(result["cache_scan"])
        self.assertEqual(
            result["cache_metrics_suppressed_reason"], "identity_changed"
        )
        self.assertIsNone(result["samples"]["duration_s"])
        self.assertEqual(
            result["samples"]["average_discharge_status"], "identity_changed"
        )

    def test_zero_sampling_duration_is_explicit(self) -> None:
        samples = [
            json.dumps(
                {
                    "timestamp_s": 10,
                    "battery": {
                        "charge_counter_uah": 1_000_000,
                        "temperature_deci_c": 350,
                        "usb_powered": False,
                    },
                }
            ),
            json.dumps(
                {
                    "timestamp_s": 10,
                    "battery": {
                        "charge_counter_uah": 990_000,
                        "temperature_deci_c": 351,
                        "usb_powered": False,
                    },
                }
            ),
        ]

        result = runtime.summarize_android_runtime("", samples)

        self.assertEqual(result["samples"]["duration_s"], 0.0)
        self.assertIsNone(result["samples"]["average_discharge_ma"])
        self.assertEqual(
            result["samples"]["average_discharge_status"], "zero_duration"
        )

    def test_all_malformed_samples_do_not_crash(self) -> None:
        result = runtime.summarize_android_runtime("", ["{bad json"])

        self.assertEqual(result["invalid_records"]["samples"], 1)
        self.assertEqual(result["parsed_records"]["samples"], 0)
        self.assertEqual(result["samples"]["count"], 0)
        self.assertEqual(result["samples"]["invalid_count"], 1)


if __name__ == "__main__":
    unittest.main()
