
import struct
nso = open(r"D:\workspace\Diablo\reference\extract\exefs\sdk.nso0", "rb").read()
gst = open(r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so", "rb").read()
sym_off = 0x20d500
size = 0x1c
nso_text_off = 0x100
a = nso[nso_text_off + sym_off: nso_text_off + sym_off + size]
print("nso bytes:", a.hex())
for base in (0x10000, 0x1000000, 0x0, 0x1000):
    cand = gst[base + sym_off: base + sym_off + size]
    print(f"  merged@{base:#x}: {cand.hex()}  match={cand == a}")
