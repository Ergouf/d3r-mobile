# D3 native keyboard/mouse RE tools

B0 workspace for the native keyboard/mouse investigation of Diablo III on the
Windows ScarletNX runtime. Nothing here patches the game or writes save data.

## Prerequisites

- Node/Python as used by the repository.
- `hactool` (to decompress `main.nso0`).
- Ghidra 12.1.x + JDK 21 (for static analysis).
- Frida 17.x Python bindings (for runtime probes).

The paths below are examples; use your own install locations.

## 1. Decompress the main NSO

```powershell
hactool -t nso --uncompressed=main.bin main.nso0
```

Expected input: `local/assets/exefs_update/main.nso0` (build
`2607A74F5DF7754CC0357B5DF7E496931355D8CA`).

## 2. Build a Ghidra-loadable AArch64 ELF

```powershell
python tools/d3-re/build_main_elf.py main.bin --out out/windows/kbm/b0/d3_main.elf
```

The NSO's 0x100-byte header is not part of the guest image. The script lays out
`.text` / `.rodata` / `.data` / `.bss` at the NSO's memory offsets so addresses
line up with the runtime's guest addresses.

## 3. Read guest state with Frida

Spawn a throwaway game process and read the known PC action strings:

```powershell
python tools/d3-re/frida_probe.py --json
```

Attach to an already running game:

```powershell
python tools/d3-re/frida_probe.py --pid <pid> --json
```

The probe:

- finds `01001B300B9BE000_code.dll`;
- calls its `snx_module` export;
- reads the `SnxModInfo` array (`main`, `sdk`, `rtld`);
- finds the host view whose size equals the `main` module size;
- scans that view for the known NSO strings and prints both host and guest
  addresses.

It does not write game memory.

Current B0 result (see `docs/windows/KBM-RE-EVIDENCE.md`):

| string | guest address |
| --- | --- |
| `LeftClickToMove` | `0x8dc985b` |
| `RightClickAttack` | `0x8e26e0b` |
| `UseCommandClickAsRightClick` | `0x8e4533b` |
| `UI_HUD_ClickPredicate` | `0x8dcf212` |
| `ControlScheme` | `0x8dc91cb` |
| `ActionBinding` | `0x8ecc112` |

## 4. Ghidra

`ghidra_analyze.ps1` imports the ELF, runs auto-analysis with an 8 GiB heap, and
runs `FindUiRefs.java` afterwards.

```powershell
.\tools\d3-re\ghidra_analyze.ps1 `
  -Elf .\out\windows\kbm\b0\d3_main.elf `
  -GhidraHome C:\tools\ghidra_12.1.4_PUBLIC `
  -JavaHome C:\tools\jdk-21
```

The B0 acceptance is the Frida probe plus the ELF; the Ghidra run is the B1
input. Do not treat a partial Ghidra analysis as evidence of absence.

## Safety

- No save writes, no `_code.dll` patches.
- Spawned probes are killed after reading unless `--keep` is given.
- All binary work products stay under `out/` (git-ignored).
