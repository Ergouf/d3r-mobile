"""Extract an APK as data into an empty directory, with a checksum inventory.

Run with Python's -I flag. Never run scripts or build tools from the output.
"""

import argparse
import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


def checked_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts:
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{i}" for i in range(1, 10))
    reserved.update(f"LPT{i}" for i in range(1, 10))
    for part in path.parts:
        if (
            part in {".", ".."}
            or any(c in part for c in ':<>"|?*')
            or part.endswith((" ", "."))
            or part.split(".", 1)[0].upper() in reserved
        ):
            raise ValueError(f"Unsafe ZIP path: {name!r}")
    return path


def extract(apk: Path, destination: Path, inventory: Path, limit: int) -> dict:
    if inventory.exists():
        raise FileExistsError(f"Inventory already exists: {inventory}")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("The extraction directory must be empty")

    with apk.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()

    with zipfile.ZipFile(apk) as archive:
        entries = archive.infolist()
        total = sum(entry.file_size for entry in entries)
        if total > limit or total + 16 * 1024 * 1024 > shutil.disk_usage(destination).free:
            raise ValueError("Archive exceeds the extraction size or free-space limit")

        paths = []
        seen = set()
        for entry in entries:
            path = checked_path(entry.filename)
            key = str(path).casefold()
            if key in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Duplicate or symlink ZIP entry: {entry.filename!r}")
            if entry.flag_bits & 1:
                raise ValueError("Encrypted ZIP entries are not supported")
            seen.add(key)
            paths.append(path)

        files = []
        for entry, relative in zip(entries, paths):
            target = destination.joinpath(*relative.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            written = 0
            with archive.open(entry) as source, target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    written += len(chunk)
                    if written > entry.file_size:
                        raise ValueError("ZIP entry exceeds its declared size")
                    output.write(chunk)
                    digest.update(chunk)
            if written != entry.file_size:
                raise ValueError("ZIP entry size does not match its declaration")
            files.append({
                "path": str(relative),
                "bytes": written,
                "sha256": digest.hexdigest(),
                "crc32": f"{entry.CRC:08x}",
            })

    report = {
        "apk": str(apk.resolve()),
        "apk_sha256": checksum,
        "extracted_to": str(destination.resolve()),
        "uncompressed_bytes": total,
        "files": files,
    }
    with inventory.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=2 * 1024**3)
    args = parser.parse_args()
    report = extract(args.apk, args.destination, args.inventory, args.limit)
    print(f"Extracted {len(report['files'])} files ({report['uncompressed_bytes']} bytes)")
    print(f"APK SHA-256: {report['apk_sha256']}")
    print(f"Inventory: {args.inventory}")


if __name__ == "__main__":
    main()
