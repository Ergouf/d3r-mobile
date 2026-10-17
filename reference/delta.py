
import random, collections
gst = open(r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so", "rb").read()
nso = open(r"D:\workspace\Diablo\reference\extract\exefs\sdk.nso0", "rb").read()
TEXT_OFF, TEXT_SZ = 0x100, 0x4e7960
random.seed(7)
deltas = collections.Counter()
matched = 0
N = 300
for _ in range(N):
    off = random.randrange(0, TEXT_SZ - 48)
    chunk = nso[TEXT_OFF+off: TEXT_OFF+off+40]
    j = gst.find(chunk)
    if j >= 0:
        matched += 1
        deltas[j - (TEXT_OFF + off)] += 1
print(f"matched {matched}/{N} 40-byte samples")
for d, c in deltas.most_common(8):
    print(f"   delta {d:#x} x{c}  (=> sdk text base {d - TEXT_OFF:#x})")
