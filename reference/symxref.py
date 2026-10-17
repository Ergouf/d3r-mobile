
from elftools.elf.elffile import ELFFile
import struct
p = r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so"
data = open(p, "rb").read()
target_off = 0x925dde   # "_ZN2nn4time10InitializeEv"
with open(p, "rb") as f:
    e = ELFFile(f)
    sec = None
    for s in e.iter_sections():
        o = s["sh_offset"]; sz = s["sh_size"]
        if o <= target_off < o + sz:
            sec = s; break
    print("containing section:", sec.name, "addr", hex(sec["sh_addr"]), "off", hex(sec["sh_offset"]))
    vaddr = sec["sh_addr"] + (target_off - sec["sh_offset"])
    print("string vaddr:", hex(vaddr))
    print("context:", data[target_off-40:target_off+60])
    ptr = struct.pack("<Q", vaddr)
    hits = []
    i = 0
    while True:
        j = data.find(ptr, i)
        if j < 0: break
        hits.append(j); i = j + 1
    print("pointer hits:", len(hits))
    for j in hits[:5]:
        print("  hit at file 0x%x, section?" % j)
        lo = max(0, j-32); hi = min(len(data), j+40)
        vals = struct.unpack("<%dQ" % ((hi-lo)//8), data[lo:hi - (hi-lo)%8])
        print("   qwords:", " ".join(hex(v) for v in vals))
