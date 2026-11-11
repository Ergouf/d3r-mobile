from __future__ import annotations
import importlib.util
import json
import sys
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "tools/collect_android_battery.py"
SPEC = importlib.util.spec_from_file_location("collect_android_battery", MODULE)
assert SPEC and SPEC.loader
collect = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collect
SPEC.loader.exec_module(collect)


def proc_stat(start="987654"):
    fields = ["0"] * 40
    fields[18] = start
    return "123 (host.validation) S " + " ".join(fields)


def sample(timestamp=10.5, process=None):
    return "\n".join([
        "@@SAMPLE", json.dumps({"monotonic_s": timestamp, "boottime_s": timestamp + 5,
                                "realtime_s": timestamp + 1000}), "@@BATTERY",
        "AC powered: false", "USB powered: false", "Wireless powered: false",
        "Dock powered: false", "Charge counter: 5179000", "temperature: 310", "voltage: 4318",
        "@@CURRENT", "Result: Parcel(",
        "0x00000000: 00000000 00000000 00000001 fffe42b0 '.............B..'",
        "0x00000010: ffffffff ffffffff                   '........        ')",
        "@@PROC", proc_stat() if process is None else process, "@@END", "",
    ])


class DeviceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.job = {"proc_stat": proc_stat(), "pid": 123, "apk_sha256": "a" * 64}
        self.start = {"monotonic_s": 10.0}

    def test_real_parcel_and_unplugged_power_state_decode(self):
        records = collect.decode_samples(sample(), self.job, self.start)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["timestamp_s"], .5)
        self.assertEqual(records[0]["battery"]["current_now_ua"], -114000)
        self.assertEqual(records[0]["battery"]["voltage_mv"], 4318)
        self.assertFalse(records[0]["battery"]["external_powered"])

    def test_missing_or_changed_process_identity_is_rejected(self):
        for value in ("", proc_stat("123456")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                collect.decode_samples(sample(process=value), self.job, self.start)

    def test_non_monotonic_or_truncated_samples_are_rejected(self):
        for raw in (sample() + sample(10.4), sample().replace("@@END", ""), ""):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                collect.decode_samples(raw, self.job, self.start)


if __name__ == "__main__":
    unittest.main()
