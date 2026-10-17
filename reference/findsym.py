
import struct

p = r"D:\workspace\Diablo\reference\extract\exefs\sdk.nso0"
d = open(p, "rb").read()
f = lambda o: struct.unpack_from("<I", d, o)[0]
text_off, text_size = f(0x10), f(0x18)
ro_off, ro_size = f(0x20), f(0x28)
print(f"text {text_off:#x}+{text_size:#x}  ro {ro_off:#x}+{ro_size:#x}")

target = b"_ZN2nn4time10InitializeEv"
tp = d.find(target, ro_off, ro_off + ro_size)
print("string at", hex(tp))

# try every 4-byte aligned slot in .ro as a possible dynsym entry
found = []
for entry in range(ro_off, ro_off + ro_size - 24, 4):
    name_off = struct.unpack_from("<I", d, entry)[0]
    if name_off == 0 or name_off >= tp - ro_off + 1: continue
    base = tp - name_off
    if base < ro_off or base >= tp: continue
    if d[base] != 0: continue
    info, other, shndx = d[entry+4], d[entry+5], struct.unpack_from("<H", d, entry+6)[0]
    value, size = struct.unpack_from("<QQ", d, entry+8)
    if info & 0xf not in (0, 1, 2, 10): continue
    if value >= text_size or value < 0x1000: continue
    if size > 0x20000: continue
    found.append((entry, name_off, base, value, size, info, shndx))

print("candidates:", len(found))
for e, no, base, val, size, info, shndx in found[:6]:
    print(f"  entry@{e:#x} st_name={no:#x} strtab_base={base:#x} value={val:#x} size={size:#x} info={info:#x} shndx={shndx}")
    # sanity: neighbouring entries should also resolve into the same table
    ok = 0
    for k in (-2, -1, 1, 2):
        e2 = e + k*24
        if not (ro_off <= e2 < ro_off + ro_size - 24): continue
        n2 = struct.unpack_from("<I", d, e2)[0]
        s2 = base + n2
        if ro_off <= s2 < ro_off + ro_size and d[s2] > 32 and d[s2] < 127:
            ok += 1
    print(f"      neighbours resolving into same strtab: {ok}/4")
