import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
data = Path(r"out/windows/kbm/b2/runtime_text.bin").read_bytes()
base = 0x8005000
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
mask = 0xFFFFFC00
ops = {
    "ldr64": 0b1111100101,
    "str64": 0b1111100100,
}
offs = [0x278, 0x280, 0x270, 0x288]
rows=[]
for off in offs:
    imm12 = off // 8
    for kind, opcode in ops.items():
        val = (opcode << 22) | (imm12 << 10)
        for i in range(0, len(data)-3, 4):
            w = struct.unpack_from("<I", data, i)[0]
            if (w & mask) != val: continue
            addr = base+i
            if not (0x8160000 <= addr <= 0x8450000): continue
            ins = next(md.disasm(data[i:i+4], addr))
            rows.append(f"{addr:#x} {ins.mnemonic} {ins.op_str}")
print("n", len(rows))
print("\n".join(rows[:120]))
Path(r"out/windows/kbm/session/round81-278.txt").write_text("\n".join(rows), encoding="utf-8")
