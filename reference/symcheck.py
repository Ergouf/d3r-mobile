
from elftools.elf.elffile import ELFFile
import itertools
p = r"D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so"
names = ["_ZN2nn4time10InitializeEv",
         "_ZN2nn4time23StandardUserSystemClock14GetCurrentTimeEPNS0_9PosixTimeE",
         "_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeE",
         "_ZN2nn2oe10InitializeEv",
         "_ZN2nn2os10InitializeEv"]
with open(p, "rb") as f:
    e = ELFFile(f)
    for sn in (".symtab", ".dynsym"):
        s = e.get_section_by_name(sn)
        print(sn, "entries:", s.num_symbols() if s else None)
    m = {}
    for sn in (".symtab", ".dynsym"):
        s = e.get_section_by_name(sn)
        if not s: continue
        for sym in s.iter_symbols():
            n = sym.name
            if n.startswith("_ZN2nn"):
                m.setdefault(n, sym["st_value"])
    print("nn2nn symbols with addresses:", len(m))
    for n in names:
        print(("  YES " if n in m else "  no  ") + n + (("  -> " + hex(m[n])) if n in m else ""))
    print("samples:")
    for n in itertools.islice(sorted(m), 6):
        print("   ", hex(m[n]), n)
