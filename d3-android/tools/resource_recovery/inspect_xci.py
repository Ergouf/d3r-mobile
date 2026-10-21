"""Index a local XCI; optional voice-NCA extraction writes only to generated output."""

import argparse
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[3]


def hfs(file, offset):
    file.seek(offset)
    magic, count, string_size, _ = struct.unpack('<4sIII', file.read(16))
    if magic != b'HFS0':
        raise ValueError('Invalid HFS0 partition')
    table = file.read(count * 64)
    names = file.read(string_size)
    start = offset + 16 + count * 64 + string_size
    for index in range(count):
        at, size, name = struct.unpack_from('<QQI', table, index * 64)
        yield names[name:].split(b'\0', 1)[0].decode(), start + at, size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='XCI input; default: the sole .xci under local/assets/game')
    parser.add_argument('--keys', type=Path, default=ROOT / 'local/keys/prod.keys')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'out/android/resource-recovery')
    parser.add_argument('--extract-voice', action='store_true', help='Extract the Chinese voice NCA into output-dir/voice-zh')
    args = parser.parse_args()
    source = args.source
    if source is None:
        candidates = sorted((ROOT / 'local/assets/game').glob('*.xci'))
        if len(candidates) != 1:
            parser.error('Pass --source when local/assets/game does not contain exactly one XCI')
        source = candidates[0]
    source = source.resolve(strict=True)
    keys_path = args.keys.resolve(strict=True)
    output = args.output_dir.resolve()
    if output.is_relative_to((ROOT / 'local').resolve()):
        parser.error('--output-dir must not be inside preserved local inputs')

    # Deferred import keeps --help usable without the optional extraction dependency.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    keys = {}
    for line in keys_path.read_text().splitlines():
        if '=' in line:
            name, value = line.split('=', 1)
            keys[name.strip()] = value.strip()
    header_key = bytes.fromhex(keys['header_key'])
    entries = []
    with source.open('rb') as file:
        file.seek(0x130)
        partition = struct.unpack('<Q', file.read(8))[0]
        secure = next(item for item in hfs(file, partition) if item[0] == 'secure')
        content = list(hfs(file, secure[1]))
        for name, offset, size in content:
            file.seek(offset)
            encrypted = file.read(0xc00)
            plain = bytearray()
            for sector in range(6):
                decrypt = Cipher(algorithms.AES(header_key), modes.XTS(sector.to_bytes(16, 'big'))).decryptor()
                plain += decrypt.update(encrypted[sector * 512:(sector + 1) * 512]) + decrypt.finalize()
            if plain[0x200:0x204] not in (b'NCA3', b'NCA2'):
                raise ValueError('Invalid decrypted NCA header')
            record = dict(name=name, offset=offset, size=size, type=plain[0x205],
                          title_id=f'{struct.unpack_from("<Q", plain, 0x210)[0]:016x}')
            entries.append(record)
            print(record['name'], record['title_id'], 'type=' + str(record['type']), 'bytes=' + str(size))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'xci-index.json').write_text(json.dumps(entries, indent=2) + '\n', encoding='utf-8')
    if args.extract_voice:
        entry = next(item for item in entries if item['title_id'] == '01001b300b9bf00b' and item['type'] == 5)
        if Path(entry['name']).name != entry['name'] or not entry['name'].endswith('.nca'):
            raise ValueError('Invalid NCA filename')
        directory = output / 'voice-zh'
        directory.mkdir(exist_ok=True)
        target = directory / entry['name']
        # Refuse replacement; preserved XCI, keys and installed voice CPKs are never written.
        with source.open('rb') as reader, target.open('xb') as writer:
            reader.seek(entry['offset'])
            remaining = entry['size']
            while remaining:
                data = reader.read(min(8 * 1024 * 1024, remaining))
                if not data:
                    raise EOFError('Unexpected end of XCI')
                writer.write(data)
                remaining -= len(data)
        print('extracted', target)


if __name__ == '__main__':
    main()
