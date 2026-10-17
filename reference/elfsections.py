
from elftools.elf.elffile import ELFFile
p = r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so"
data = open(p, "rb").read()
print("file size", hex(len(data)))
for magic in (b"MOD0", b".mod0"):
    i = data.find(magic)
    print(magic, "->", hex(i) if i >= 0 else "absent")
with open(p, "rb") as f:
    e = ELFFile(f)
    print("\nsections:")
    for s in e.iter_sections():
        if s.name in ("", None): continue
        print("  %-18s type=%-18s size=%-10d off=%#x" % (s.name, s["sh_type"], s["sh_size"], s["sh_offset"]))
    print("\nsegments:")
    for s in e.iter_segments():
        print("  %-14s vaddr=%#x filesz=%#x memsz=%#x" % (s["p_type"], s["p_vaddr"], s["p_filesz"], s["p_memsz"]))
