
import struct, json

def load(path):
    d = open(path, "rb").read()
    f = lambda o: struct.unpack_from("<I", d, o)[0]
    return d, f(0x10), f(0x18), f(0x20), f(0x28)

def calibrate(d, ro_off, ro_size):
    names = [b"__nnDetailNintendoSdkRuntimeObjectFile", b"__rel_dyn_end", b"__rel_dyn_start",
             b"__rel_plt_end", b"__rel_plt_start"]
    so = [d.find(n, ro_off, ro_off + ro_size) for n in names]
    assert all(x >= 0 for x in so), so
    for e in range(ro_off, ro_off + ro_size - 24 * len(names), 4):
        n0 = struct.unpack_from("<I", d, e)[0]
        if n0 == 0 or n0 > so[0] - ro_off: continue
        base = so[0] - n0
        if base < ro_off or base >= so[0] or d[base] != 0: continue
        if all(base + struct.unpack_from("<I", d, e + 24*k)[0] == so[k] for k in range(1, len(names))):
            return e, base
    raise SystemExit("no dynsym array")

p = r"D:\workspace\Diablo\reference\extract\exefs_update\sdk.nso0"
d, text_off, text_sz, ro_off, ro_sz = load(p)
e0, strbase = calibrate(d, ro_off, ro_sz)
count = (strbase - e0) // 24
print(f"dynsym {e0:#x} strtab {strbase:#x} count={count}")
syms = {}
for i in range(count):
    o = e0 + 24*i
    name_off, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", d, o)
    if name_off == 0: continue
    s = strbase + name_off
    if s >= strbase + (ro_off + ro_sz - strbase): continue
    end = d.find(b"\0", s, s + 512)
    if end < 0: continue
    try: nm = d[s:end].decode("utf-8")
    except UnicodeDecodeError: continue
    if nm: syms[nm] = value
print("symbols:", len(syms))
json.dump(syms, open(r"D:\workspace\Diablo\reference\extract\exefs_update\sdk.symbols.json", "w"))

SDK_BASE = 0x10000
gst = open(r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so", "rb").read()
for probe in ("_ZN2nn4time10InitializeEv", "_ZN2nn4time23StandardUserSystemClock3nowEv",
              "_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22AdditionalInfoERKNS0_9PosixTimeE",
              "_ZN2nn2oe10InitializeEv", "_ZN2nn2sf4cmif6client6detail13CmifProxyImpl"):
    for k in syms:
        if k.startswith(probe if probe.endswith("ProxyImpl") else probe):
            v = syms[k]
            gva = SDK_BASE + v
            nso_file = text_off + v
            chunk = d[nso_file:nso_file+16]
            guest_chunk = gst[(gva - 0x10000) + 0x4000: (gva - 0x10000) + 0x4000 + 16]
            print(f"  {k[:58]:58s} sym={v:#08x} guest={gva:#08x} bytes_match={guest_chunk == chunk}")
            break
