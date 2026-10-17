
import random, collections, struct
gst = open(r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so","rb").read()
p = r"D:\workspace\Diablo\reference\extract\exefs_update\main.nso0"
nso = open(p,"rb").read()
f = lambda o: struct.unpack_from("<I", nso, o)[0]
text_off, text_sz = f(0x10), f(0x18)
print("update main: text_off", hex(text_off), "text_sz", hex(text_sz))
random.seed(3)
deltas = collections.Counter(); matched = 0; N = 300
for _ in range(N):
    off = random.randrange(0, text_sz - 48)
    chunk = nso[text_off+off: text_off+off+40]
    j = gst.find(chunk)
    if j >= 0:
        matched += 1
        deltas[j - (text_off + off)] += 1
print(f"matched {matched}/{N}")
for d, c in deltas.most_common(5):
    print(f"   delta {d:#x} x{c}")
