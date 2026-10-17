
import struct
p = r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so"
data = open(p, "rb").read()
target = 0x925dde
# find blob start: back up to a previous NUL
s = target
while s > 0 and data[s-1] != 0: s -= 1
print("string start file off", hex(s), "len", target - s + 30)
for label, val in (("rel_to_blob0x6f564a", target - 0x6f564a), ("u32 vaddr", (0x931dde) & 0xffffffff), ("u32 fileoff", target & 0xffffffff)):
    pat = struct.pack("<I", val)
    i = 0; hits = []
    while True:
        j = data.find(pat, i)
        if j < 0: break
        hits.append(j); i = j + 1
        if len(hits) > 40: break
    print(f"{label} = {hex(val)}: {len(hits)} hits", [hex(x) for x in hits[:6]])
# how big is the contiguous name blob?
i = 0x6f564a
while i < len(data):
    k = data.find(b"\x00", i)
    if k < 0: break
    nxt = data[k+1:k+1+6]
    if not nxt.startswith(b"_ZN2nn"): 
        print("blob ends after", hex(k+1)); break
    i = k + 1
print("blob span", hex(0x6f564a), "->", hex(i))
