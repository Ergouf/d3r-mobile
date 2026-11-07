"""Verify saved artisan business evidence; no Frida or game input.

This deliberately distinguishes native-keyboard training from the unfinished
mouse confirmation path, and verifies the local fixture's accepted game load.
Requires the local evidence/checkpoints recorded by the current handoff.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "out/windows/kbm/session/artisan-business-verification.json"


def main() -> int:
    report = json.loads(REPORT.read_text("utf-8"))
    data = {}
    for name, evidence in report["evidence"].items():
        path = Path(evidence["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"], name
        data[name] = json.loads(path.read_text("utf-8"))
    before = data["business-mystic-training-before.json"]
    after = data["business-mystic-training-after.json"]
    disabled = data["business-mystic-training-disabled.json"]
    checks = 0

    def check(name: str, condition: bool) -> None:
        nonlocal checks
        assert condition, name
        checks += 1
        print("PASS " + name)

    def text(tree: dict, key: str) -> str:
        return next(i["text"] for i in tree["items"] if str(i["key"]) == key and i["visible"])

    gold, level, legend = "14190085993729748614", "3118840645059350727", "13888055703122506020"
    check("same-executable-evidence", all(t["build"]["exe_sha256"] == report["build"]
                                         for t in (before, after, disabled)))
    check("gold-decreased-by-500", text(before,gold) == "1447 {icon:gold}" and
          text(after,gold) == "947 {icon:gold}")
    check("mystic-level-increased", text(before,level) == "1" and text(after,level) == "2")
    check("enabled-training-hint-disappears", "button1" in text(before,legend) and "button1" not in text(after,legend))
    check("insufficient-gold-repeat-does-not-train", text(disabled,gold) == text(after,gold) and
          text(disabled,level) == text(after,level))
    check("mouse-confirmation-not-claimed", "not complete" in report["training_scope"])
    fixture = json.loads(Path(report["fixture_manifest"]).read_text("utf-8"))
    check("format-and-restoration-verified", fixture["xor_noop_byte_exact"] and
          fixture["protobuf_noop_byte_exact"] and fixture["restore_rehearsal_byte_exact"] and
          fixture["other_fields_byte_exact_when_counts_restored"])
    check("only-account-file-modified", len(fixture["changed_files"]) == 1 and
          Path(fixture["changed_files"][0]).name == "account.dat")
    check("fixture-game-load-validated", fixture["installed"] and fixture["game_load_validated"])
    loaded = data["fixture-inventory-loaded.json"]
    check("million-gold-and-100-shards-observed", loaded["groupIndex"] == 0 and loaded["pageSelected"] == 0 and
          any(re.match(r"^1000000 \{icon:gold\}  100/500 \{icon:x1_shard\}$", t["text"])
              for t in loaded["texts"]))
    original = Path(fixture["source_checkpoint"])
    check("original-cold-checkpoint-still-intact", all(
        hashlib.sha256((original / rel).read_bytes()).hexdigest() == want
        for rel,want in fixture["original_file_sha256"].items()))
    print(f"{checks} business evidence checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
