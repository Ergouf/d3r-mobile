
"""Extract the dynamic symbol table from an already decompressed NSO0 image."""
import argparse
import struct
import json
from pathlib import Path

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

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("input", type=Path, help="Uncompressed sdk/main NSO0 file")
    cli.add_argument("--output", type=Path, help="Defaults to out/android/symbols/<input>.symbols.json")
    args = cli.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output or root / "out/android/symbols" / (args.input.stem + ".symbols.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(parse(args.input), indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
