
import struct
gst = open(r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so", "rb").read()
print("guest size", hex(len(gst)))
# 1) locate MOD0 occurrences and check the mod0 field signature from sdk.nso0
target = struct.pack("<6I", 0xaf6d00, 0xb15ff8, 0xc0b250, 0x9cab58, 0x9f9a64, 0x0)
i = 0
hits = []
while True:
    j = gst.find(target, i)
    if j < 0: break
    hits.append(j); i = j + 1
print("sdk MOD0 body hits:", [hex(h) for h in hits])
for h in hits:
    print("   MOD0 magic at", hex(h - 8), "bytes:", gst[h-12:h+32].hex())
# 2) also search for the first 32 bytes of sdk text
nso = open(r"D:\workspace\Diablo\reference\extract\exefs\sdk.nso0", "rb").read()
head = nso[0x100:0x100+32]
print("\nsdk text head:", head.hex())
k = gst.find(head)
print("sdk text head in guest:", hex(k) if k >= 0 else "absent")
if k >= 0:
    print("  => sdk text file offset maps guest", hex(k), "so delta =", hex(k - 0x100))
