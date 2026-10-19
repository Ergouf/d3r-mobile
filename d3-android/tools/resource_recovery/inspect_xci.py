from pathlib import Path
import json, struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

root = Path(__file__).resolve().parents[3]
source = next(root.glob('*.xci'))
keys = dict(line.split('=', 1) for line in (root / 'prod.keys').read_text().splitlines() if '=' in line)
header_key = bytes.fromhex(keys['header_key '].strip()) if 'header_key ' in keys else bytes.fromhex(next(v for k,v in keys.items() if k.strip() == 'header_key').strip())
def hfs(file, offset):
    file.seek(offset); magic, count, string_size, _ = struct.unpack('<4sIII', file.read(16))
    assert magic == b'HFS0'
    table = file.read(count * 64); names = file.read(string_size)
    start = offset + 16 + count * 64 + string_size
    for i in range(count):
        at, size, name = struct.unpack_from('<QQI', table, i * 64)
        yield names[name:].split(b'\0', 1)[0].decode(), start + at, size
entries = []
with source.open('rb') as file:
    file.seek(0x130); partition = struct.unpack('<Q', file.read(8))[0]
    secure = next(v for v in hfs(file, partition) if v[0] == 'secure')
    content = list(hfs(file, secure[1]))
    for name, offset, size in content:
        file.seek(offset); encrypted = file.read(0xc00)
        plain = b''
        for sector in range(6):
            decrypt = Cipher(algorithms.AES(header_key), modes.XTS(sector.to_bytes(16,'big'))).decryptor()
            plain += decrypt.update(encrypted[sector*512:(sector+1)*512]) + decrypt.finalize()
        assert plain[0x200:0x204] in (b'NCA3',b'NCA2')
        record = dict(name=name, offset=offset, size=size, type=plain[0x205], title_id=f'{struct.unpack_from("<Q", plain, 0x210)[0]:016x}')
        entries.append(record)
        print(record['name'], record['title_id'], 'type='+str(record['type']), 'bytes='+str(size))
Path(__file__).with_name('xci-index.json').write_text(json.dumps(entries, indent=2))
import sys
if '--extract-voice' in sys.argv:
    entry = next(v for v in entries if v['title_id'] == '01001b300b9bf00b' and v['type'] == 5)
    directory = root / 'reference/extract/voice_zh'; directory.mkdir(exist_ok=True)
    target = directory / entry['name']
    if not target.exists() or target.stat().st_size != entry['size']:
        with source.open('rb') as reader, target.open('wb') as writer:
            reader.seek(entry['offset']); remaining = entry['size']
            while remaining:
                data = reader.read(min(8*1024*1024, remaining))
                if not data: raise IOError('unexpected EOF')
                writer.write(data); remaining -= len(data)
    print('extracted', target)
