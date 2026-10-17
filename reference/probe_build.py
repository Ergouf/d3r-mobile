
gst = open(r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so", "rb").read()
pat = bytes.fromhex("fd7bbfa9fd030091e003003205000094007c4092fd7bc1a8c0035fd6")
i = gst.find(pat)
print("nn::time::Initialize body in guest:", hex(i) if i >= 0 else "ABSENT")
# count how much of sdk text appears: sample 8 chunks
nso = open(r"D:\workspace\Diablo\reference\extract\exefs\sdk.nso0", "rb").read()
import random
random.seed(1)
hits = 0
for _ in range(20):
    off = 0x100 + random.randrange(0, 0x4e7960 - 64)
    chunk = nso[off:off+32]
    if gst.find(chunk) >= 0: hits += 1
print(f"sdk .text 32-byte samples found in guest: {hits}/20")
