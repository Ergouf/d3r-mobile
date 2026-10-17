
import struct, json

class Nso:
    def __init__(self, path):
        self.d = d = open(path, "rb").read()
        assert d[:4] == b"NSO0"
        f = lambda o: struct.unpack_from("<I", d, o)[0]
        self.text = (f(0x10), f(0x14), f(0x18))
        self.ro   = (f(0x20), f(0x24), f(0x28))
        self.data = (f(0x30), f(0x34), f(0x38))
        self.bss  = f(0x3C)
    def to_file(self, vaddr):
        for off, mem, size in (self.text, self.ro, self.data):
            if mem <= vaddr < mem + size:
                return off + (vaddr - mem)
        raise ValueError(f"{vaddr:#x} outside sections")

def parse(path):
    n = Nso(path)
    hit = n.d.find(b"MOD0")
    print(f"{path}  MOD0@{hit:#x}")
    dyn, bss_s, bss_e = struct.unpack_from("<3I", n.d, hit + 4)
    df = n.to_file(dyn)
    print(f"  dynamic vaddr={dyn:#x} file={df:#x}")
    tags = {}
    for i in range(40):
        tag, val = struct.unpack_from("<QQ", n.d, df + i * 16)
        if tag == 0: break
        tags[tag] = val
    print("  tags:", {hex(k): hex(v) for k, v in tags.items() if k in (4,5,6,11)})
    symtab, strtab, hashtab = tags.get(6), tags.get(5), tags.get(4)
    syment = tags.get(11, 24)
    hf = n.to_file(hashtab)
    nchain = struct.unpack_from("<I", n.d, hf + 4)[0]
    sf, tf = n.to_file(symtab), n.to_file(strtab)
    out = {}
    for i in range(nchain):
        name_off, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", n.d, sf + i * syment)
        if name_off == 0: continue
        end = n.d.index(b"\0", tf + name_off)
        name = n.d[tf + name_off:end].decode("utf-8", "replace")
        if name: out[name] = value
    print(f"  symbols={len(out)}")
    return out

for name in ("sdk", "main"):
    syms = parse(rf"D:\workspace\Diablo\reference\extract\exefs\{name}.nso0")
    if syms:
        json.dump(syms, open(rf"D:\workspace\Diablo\reference\extract\exefs\{name}.symbols.json", "w"))
        for p in ("_ZN2nn4time10InitializeEv", "_ZN2nn4time23StandardUserSystemClock3nowEv", "nnMain", "malloc"):
            print("    ", p[:50], "->", hex(syms[p]) if p in syms else "MISSING")
    print()
