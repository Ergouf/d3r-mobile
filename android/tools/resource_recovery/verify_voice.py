"""Hash the preserved Chinese voice CPKs; optionally compare them with one explicit Android device."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
REMOTE = '/data/local/tmp/d3romfs/AddOnContent/11/'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'local/assets/android/voice-zh')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/android/resource-recovery/zh-voice-manifest.json')
    parser.add_argument('--local-only', action='store_true', help='Hash local inputs without connecting to a device or writing its marker')
    parser.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'), help='Explicit adb serial (or ANDROID_SERIAL)')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to((ROOT / 'local').resolve()):
        parser.error('--output must not be inside preserved local inputs')
    files = sorted(source.glob('ztCN_*.cpk'))
    if len(files) != 14:
        parser.error(f'Expected 14 Chinese voice CPKs, found {len(files)} in {source}')
    if not args.local_only and not args.serial:
        parser.error('Pass --serial (or set ANDROID_SERIAL), or use --local-only')
    adb = ['adb', '-s', args.serial] if args.serial else []
    records = []
    for file in files:
        with file.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if not args.local_only:
            actual = subprocess.check_output([*adb, 'shell', 'sha256sum', REMOTE + file.name], text=True).split()[0]
            if actual != digest:
                raise ValueError('Device SHA-256 mismatch: ' + file.name)
        records.append(dict(name=file.name, bytes=file.stat().st_size, sha256=digest))
        print(('local verified' if args.local_only else 'device verified'), file.name, flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    if not args.local_only:
        subprocess.run([*adb, 'shell', 'tee', REMOTE + '.d3-content-complete'],
                       input='01001b300b9bf00b\n', text=True, check=True)
    print('manifest:', output)


if __name__ == '__main__':
    main()
