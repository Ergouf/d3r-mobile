
import struct

p = r"D:\workspace\Diablo\reference\extract\exefs\sdk.nso0"
d = open(p, "rb").read()
f = lambda o: struct.unpack_from("<I", d, o)[0]
text_size = f(0x18)
ro_off, ro_size = f(0x20), f(0x28)

names = [b"__nnDetailNintendoSdkRuntimeObjectFile", b"__rel_dyn_end", b"__rel_dyn_start",
         b"__rel_plt_end", b"__rel_plt_start"]
soffs = []
for n in names:
    i = d.find(n, ro_off, ro_off + ro_size)
    soffs.append(i)
    print(n.decode(), "->", hex(i))
if -1 in soffs: raise SystemExit("missing name")

best = None
for e in range(ro_off, ro_off + ro_size - 24*len(names), 4):
    n0 = struct.unpack_from("<I", d, e)[0]
    if n0 == 0 or n0 > soffs[0] - ro_off: continue
    base = soffs[0] - n0
    if base < ro_off or base >= soffs[0] or d[base] != 0: continue
    ok = True
    for k in range(1, len(names)):
        nk = struct.unpack_from("<I", d, e + 24*k)[0]
        if base + nk != soffs[k]: ok = False; break
    if ok:
        best = (e, base)
        break

print("dynsym array:", hex(best[0]) if best else "NOT FOUND", "strtab base:", hex(best[1]) if best else "-")
if best:
    e0, base = best
    # walk backwards to symbol 0 if needed, then dump our target
    idx = (e0 - ro_off) // 24
    print("first calibrated index:", idx)
    target = b"_ZN2nn4time10InitializeEv"
    toff = d.find(target, ro_off, ro_off + ro_size)
    rel = toff - base
    hits = []
    for i in range(0, (ro_off + ro_size - e0)//24):
        n = struct.unpack_from("<I", d, e0 + 24*i)[0]
        if n == rel:
            info, other, shndx = d[e0+24*i+4], d[e0+24*i+5], struct.unpack_from("<H", d, e0+24*i+6)[0]
            val, size = struct.unpack_from("<QQ", d, e0+24*i+8)
            hits.append((i, val, size, info, shndx))
    print("target entries:", [(i, hex(v), hex(s), hex(inf), sh) for i, v, s, inf, sh in hits[:5]])
