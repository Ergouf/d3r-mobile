
from elftools.elf.elffile import ELFFile
import struct
p = r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so"
data = open(p, "rb").read()
target_off = 0x925dde
with open(p, "rb") as f:
    e = ELFFile(f)
    seg = None
    for s in e.iter_segments():
        o = s["p_offset"]; sz = s["p_filesz"]
        if s["p_type"] == "PT_LOAD" and o <= target_off < o + sz:
            seg = s; break
    print("segment vaddr", hex(seg["p_vaddr"]), "off", hex(seg["p_offset"]), "filesz", hex(seg["p_filesz"]))
    vaddr = seg["p_vaddr"] + (target_off - seg["p_offset"])
    print("string vaddr:", hex(vaddr))
    print("context:", data[target_off-48:target_off+64])
    ptr = struct.pack("<Q", vaddr)
    hits = []
    i = 0
    while True:
        j = data.find(ptr, i)
        if j < 0: break
        hits.append(j); i = j + 1
    print("pointer hits:", len(hits))
    for j in hits[:6]:
        lo = max(0, j - 24); n = 8
        vals = struct.unpack("<%dQ" % n, data[lo:lo + n*8])
        print("  hit file 0x%x ->" % j, " ".join(hex(v) for v in vals))
