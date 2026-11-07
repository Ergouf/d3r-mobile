"""Read account currencies, crafter levels and hero item metadata without writes.

Uses the recorded clean D3Edit source. Output contains metadata/hashes only.
Live files are read twice for stability; cross-file atomicity requires a cold
checkpoint, so pair live reports with the same-process UI before/after evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
D3EDIT = ROOT / "local/tools/d3edit-clean"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--directory", type=Path, help="save user directory; defaults to the installed test fixture")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError("preserve existing evidence; choose a new output")
    if args.directory is None:
        fixture = json.loads((ROOT / "local/saves/kbm-artisan-rich-v3/fixture-manifest.json").read_text("utf-8"))
        directory = Path(fixture["installed_target"]).parent
    else:
        directory = args.directory.resolve()
    provenance = json.loads((ROOT / "local/tools/d3edit-source-provenance.json").read_text("utf-8"))
    for rel, expected in provenance["file_sha256"].items():
        if sha((D3EDIT / rel).read_bytes()) != expected:
            raise RuntimeError("source snapshot differs: " + rel)
    if subprocess.check_output(["git", "-C", str(D3EDIT), "status", "--porcelain"]):
        raise RuntimeError("D3Edit source checkout is not clean")
    os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(D3EDIT))
    import Account_pb2
    import Hero_pb2
    import D3Edit

    report = {"scope": __doc__, "directory": str(directory), "files": {}}

    def read(path, cls):
        raw = path.read_bytes()
        if raw != path.read_bytes():
            raise RuntimeError("file changed while reading: " + str(path))
        plain = D3Edit.decrypt_save(raw)
        message = cls()
        count = message.ParseFromString(plain)
        meta = {"path": str(path), "bytes": len(raw), "sha256": sha(raw),
                "mtime_ns": path.stat().st_mtime_ns, "complete_parse": count == len(plain),
                "initialized": message.IsInitialized(), "protobuf_noop_byte_exact": message.SerializeToString() == plain,
                "xor_noop_byte_exact": D3Edit.encrypt_save(plain) == raw, "version": message.version}
        report["files"][str(path.relative_to(directory))] = meta
        if not all(meta[k] for k in ("complete_parse", "initialized", "protobuf_noop_byte_exact", "xor_noop_byte_exact")):
            raise RuntimeError("unsupported or unstable save format: " + str(path))
        return message

    def item(i):
        g = i.generator
        return {"id": f"{i.id.id_high:016x}:{i.id.id_low:016x}",
                "slot": i.item_slot, "square": i.square_index, "hireling_class": i.hireling_class,
                "gbid": g.gb_handle.gbid, "seed": g.seed, "stack": g.stack_size,
                "durability": g.durability, "max_durability": g.max_durability,
                "affixes": list(g.base_affixes), "dye": g.dye_type, "transmog": g.transmog_gbid,
                "enchanted_affix_old": g.enchanted_affix_old, "enchanted_affix_new": g.enchanted_affix_new,
                "enchanted_affix_count": g.enchanted_affix_count, "sockets": i.used_socket_count,
                "generator_sha256": sha(g.SerializeToString())}

    account = read(directory / "account.dat", Account_pb2.SavedDefinition)
    report["partitions"] = [{"id": p.partition_id,
        "currencies": {str(c.id): c.count for c in p.currency_data.currency},
        "crafter_levels": [c.level for c in p.crafter_data.crafter_data],
        "items": [item(i) for i in p.items.items]} for p in account.partitions]
    report["heroes"] = []
    for path in sorted((directory / "heroes").glob("*.dat")):
        hero = read(path, Hero_pb2.SavedDefinition)
        report["heroes"].append({"file": path.name, "name": hero.digest.hero_name,
                                 "level": hero.digest.level, "items": [item(i) for i in hero.items.items]})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"partitions": [{k: p[k] for k in ("id", "currencies", "crafter_levels")} for p in report["partitions"]],
                      "heroes": [{"file": h["file"], "level": h["level"], "items": len(h["items"])} for h in report["heroes"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
