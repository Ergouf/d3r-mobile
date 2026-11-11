"""Prepare a local-only artisan test save from a hash-verified checkpoint.

Uses the complete, clean D3Edit source snapshot to decode the XOR/protobuf
account. Changes currency counts by ID, verifies a byte-exact no-op roundtrip,
preserves every other file/field, and rehearses byte-exact backup restoration.
Does not install the candidate, touch an active save, or modify hero data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LOCAL = (ROOT / "local/saves").resolve()
D3EDIT = ROOT / "local/tools/d3edit-clean"
PROVENANCE = ROOT / "local/tools/d3edit-source-provenance.json"
CURRENCIES = {0: "gold", 1: "blood_shards", 3: "reusable_parts", 4: "arcane_dust",
              5: "veiled_crystals", 6: "deaths_breath", 7: "forgotten_souls"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(path: Path) -> Path:
    result = path.resolve()
    if result == LOCAL or not result.is_relative_to(LOCAL):
        raise ValueError("source/destination must be dedicated folders inside local/saves")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True, help="checkpoint with backup-manifest.json")
    ap.add_argument("--destination", type=Path, required=True, help="new fixture folder in local/saves")
    ap.add_argument("--gold", type=int, default=1000000)
    ap.add_argument("--materials", type=int, default=1000)
    ap.add_argument("--blood-shards", type=int, default=100)
    args = ap.parse_args()
    if not (0 <= args.gold <= 100000000 and 0 <= args.materials <= 1000000 and
            0 <= args.blood_shards <= 500):
        ap.error("amount outside the bounded test-fixture range")
    source, destination = local_path(args.source), local_path(args.destination)
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing fixture")

    provenance = json.loads(PROVENANCE.read_text("utf-8"))
    for rel, want in provenance["file_sha256"].items():
        if digest(D3EDIT / rel) != want:
            raise RuntimeError("D3Edit source snapshot changed: " + rel)
    commit = subprocess.check_output(["git", "-C", str(D3EDIT), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(D3EDIT), "status", "--porcelain"])
    if commit != provenance["git_commit"] or status:
        raise RuntimeError("D3Edit checkout is not the recorded clean snapshot")
    archive = ROOT / provenance["archive"]
    if digest(archive) != provenance["archive_sha256"]:
        raise RuntimeError("D3Edit source archive checksum mismatch")

    backup = json.loads((source / "backup-manifest.json").read_text("utf-8"))
    expected = backup["sha256"]
    for rel, want in expected.items():
        file = (source / rel).resolve()
        if not file.is_relative_to(source) or digest(file) != want:
            raise RuntimeError("checkpoint path/hash mismatch: " + rel)
    accounts = [rel for rel in expected if Path(rel).name == "account.dat"]
    if len(accounts) != 1:
        raise RuntimeError("expected exactly one account in this checkpoint")

    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import Account_pb2
    import D3Edit

    account_rel = accounts[0]
    raw = (source / account_rel).read_bytes()
    plain = D3Edit.decrypt_save(raw)
    account = Account_pb2.SavedDefinition()
    consumed = account.ParseFromString(plain)
    if consumed != len(plain) or not account.IsInitialized():
        raise RuntimeError("incomplete or uninitialized protobuf account")
    if D3Edit.encrypt_save(plain) != raw or account.SerializeToString() != plain:
        raise RuntimeError("no-op decode/encode is not byte exact; refuse modification")
    partitions = [p for p in account.partitions if p.partition_id == 0]
    if len(partitions) != 1:
        raise RuntimeError("normal partition 0 is ambiguous/missing")
    currencies = {c.id: c for c in partitions[0].currency_data.currency}
    if len(currencies) != len(partitions[0].currency_data.currency):
        raise RuntimeError("duplicate currency IDs")
    updates = {0: args.gold, 1: args.blood_shards,
               **{i: args.materials for i in (3, 4, 5, 6, 7)}}
    before = {i: currencies[i].count for i in updates}
    for currency_id, amount in updates.items():
        currencies[currency_id].count = amount
    encoded = account.SerializeToString()
    encrypted = D3Edit.encrypt_save(encoded)
    check = Account_pb2.SavedDefinition()
    if (D3Edit.decrypt_save(encrypted) != encoded or
            check.ParseFromString(encoded) != len(encoded) or not check.IsInitialized() or
            check.SerializeToString() != encoded):
        raise RuntimeError("candidate cannot be decoded completely")
    checked_partition = next(p for p in check.partitions if p.partition_id == 0)
    checked_counts = {c.id: c.count for c in checked_partition.currency_data.currency}
    for currency_id, amount in updates.items():
        if checked_counts[currency_id] != amount:
            raise RuntimeError("currency update mismatch")
        currencies[currency_id].count = before[currency_id]
    if account.SerializeToString() != plain:
        raise RuntimeError("a non-whitelisted protobuf field changed")

    save, restore = destination / "save", destination / "restore-check"
    for rel in expected:
        for root in (save, restore):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target)
    (save / account_rel).write_bytes(encrypted)
    result_hashes = {rel: digest(save / rel) for rel in expected}
    changed = [rel for rel in expected if result_hashes[rel] != expected[rel]]
    if changed != [account_rel]:
        raise RuntimeError("unexpected changed files: " + str(changed))
    # Rehearse restoration with the edited bytes in a separate local copy.
    shutil.copyfile(save / account_rel, restore / account_rel)
    shutil.copyfile(source / account_rel, restore / account_rel)
    if any(digest(restore / rel) != want for rel, want in expected.items()):
        raise RuntimeError("backup restoration hash verification failed")
    report = {
        "source_checkpoint": str(source), "source_provenance": str(PROVENANCE),
        "source_commit": commit, "save_format": "XOR-encrypted protobuf SavedDefinition",
        "account_version": account.version, "protobuf_complete_and_initialized": True,
        "xor_noop_byte_exact": True, "protobuf_noop_byte_exact": True,
        "integrity": "Entire decrypted file parses as protobuf; D3Edit has no separate CRC envelope. "
                     "SHA-256 verifies copied/encoded bytes. Candidate game-load validation remains pending.",
        "changes": [{"id": i, "name": CURRENCIES[i], "before": before[i], "after": amount}
                    for i, amount in updates.items()],
        "changed_files": changed, "original_file_sha256": expected,
        "candidate_file_sha256": result_hashes,
        "original_plaintext_sha256": hashlib.sha256(plain).hexdigest(),
        "candidate_plaintext_sha256": hashlib.sha256(encoded).hexdigest(),
        "other_fields_byte_exact_when_counts_restored": True,
        "restore_rehearsal_byte_exact": True, "installed": False,
    }
    (destination / "fixture-manifest.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps({"destination": str(destination), "changes": report["changes"],
                      "restore_verified": True, "installed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
