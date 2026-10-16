"""Unit tests for d3-android/tools/extract_apk.py (stdlib unittest).

Run: python -I tests/test_extract_apk.py -v
Fixtures are generated ZIPs in temporary directories; no real APK is touched.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "extract_apk.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("extract_apk_under_test", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()


class ExtractApkTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def make_apk(self, entries, name="sample.apk"):
        apk = self.root / name
        with zipfile.ZipFile(apk, "w") as archive:
            for entry in entries:
                if isinstance(entry, zipfile.ZipInfo):
                    archive.writestr(entry, b"payload")
                elif isinstance(entry, tuple):
                    archive.writestr(entry[0], entry[1])
                else:
                    archive.writestr(entry, b"payload")
        return apk

    def extract(self, apk, limit=2**31, dest="out", inventory="inventory.json"):
        return tool.extract(
            apk, self.root / dest, self.root / inventory, limit
        )

    def assertRejected(self, entries, limit=2**31):
        apk = self.make_apk(entries)
        with self.assertRaises(ValueError):
            self.extract(apk, limit=limit)
        self.assertFalse((self.root / "out" / "evil.txt").exists())

    def test_extracts_files_and_writes_hash_inventory(self):
        blobs = {"assets/data.bin": b"\x00\x01\x02binary", "classes.dex": b"dex-bytes"}
        apk = self.make_apk([("assets/", b"")] + list(blobs.items()))
        report = self.extract(apk)

        self.assertEqual(report["apk"], str(apk.resolve()))
        self.assertEqual(
            report["apk_sha256"], hashlib.sha256(apk.read_bytes()).hexdigest()
        )
        self.assertEqual(report["extracted_to"], str((self.root / "out").resolve()))
        self.assertEqual(report["uncompressed_bytes"], sum(map(len, blobs.values())))

        by_path = {item["path"]: item for item in report["files"]}
        self.assertEqual(set(by_path), set(blobs))
        for name, data in blobs.items():
            self.assertEqual(by_path[name]["bytes"], len(data))
            self.assertEqual(by_path[name]["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(
                by_path[name]["crc32"], f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
            )
            self.assertEqual((self.root / "out" / name).read_bytes(), data)
        inventory = json.loads((self.root / "inventory.json").read_text("utf-8"))
        self.assertEqual(inventory, report)

    def test_rejects_parent_traversal(self):
        for name in ("../evil.txt", "a/../../evil.txt", "..", "assets/../../evil.txt"):
            with self.subTest(name=name):
                self.assertRejected([name])

    def test_rejects_absolute_paths(self):
        for name in ("/etc/passwd", "/evil.txt", "a//../../evil.txt", "//evil.txt"):
            with self.subTest(name=name):
                self.assertRejected([name])

    def test_rejects_windows_drive_backslash_and_device_names(self):
        rejected = [
            "C:/evil.txt", "c:/evil.txt", "C:", "C:evil.txt", "sub\\evil.txt",
            "\\evil.txt", "a\\..\\evil.txt", "CON", "con.txt", "NUL", "aux.bin",
            "COM1", "com9.txt", "LPT1", "lpt2.log", "PRN.dat",
            "trailing.", "trailing ", "pipe|name", "star*name", "question?name",
            'quote"name', "less<name", "greater>name",
        ]
        for name in rejected:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    tool.checked_path(name)

    def test_rejects_symlink_entry(self):
        link = zipfile.ZipInfo("assets/link")
        link.external_attr = 0o120777 << 16
        apk = self.make_apk([link])
        with self.assertRaises(ValueError):
            self.extract(apk)
        self.assertFalse((self.root / "out" / "assets" / "link").exists())

    def test_rejects_casefold_duplicate_entries(self):
        apk = self.make_apk([("Assets/Data.bin", b"one"), ("assets/data.BIN", b"two")])
        with self.assertRaises(ValueError):
            self.extract(apk)
        self.assertFalse((self.root / "out").joinpath("Assets").exists())

    def test_rejects_nonempty_destination(self):
        apk = self.make_apk([("classes.dex", b"dex")])
        (self.root / "out").mkdir()
        (self.root / "out" / "keep.txt").write_text("existing", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.extract(apk)
        self.assertEqual((self.root / "out" / "keep.txt").read_text("utf-8"), "existing")

    def test_rejects_existing_inventory(self):
        apk = self.make_apk([("classes.dex", b"dex")])
        (self.root / "inventory.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.extract(apk)

    def test_rejects_archive_over_size_limit(self):
        apk = self.make_apk([("classes.dex", b"x" * 4096)])
        with self.assertRaises(ValueError):
            self.extract(apk, limit=1024)
        self.assertFalse((self.root / "out" / "classes.dex").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
