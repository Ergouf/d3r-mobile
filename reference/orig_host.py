
from elftools.elf.elffile import ELFFile
p = r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3host.so"
data = open(p, "rb").read()
print("size", hex(len(data)))
with open(p, "rb") as f:
    e = ELFFile(f)
    for sn in (".symtab", ".dynsym"):
        s = e.get_section_by_name(sn)
        print(sn, "entries:", s.num_symbols() if s else None)
    s = e.get_section_by_name(".symtab") or e.get_section_by_name(".dynsym")
    if s:
        names = [sym.name for sym in s.iter_symbols() if sym.name]
        print("first 40 symbols:", names[:40])
        for n in names:
            if "time" in n.lower() or "shmem" in n.lower() or "shared" in n.lower():
                print("  *", n)
for probe in (b"GetSharedMemory", b"nn::time", b"_ZN2nn4time", b"QueryMemory", b"MapSharedMemory", b"state == 0"):
    i = data.find(probe)
    print(probe, "->", hex(i) if i >= 0 else "absent")
