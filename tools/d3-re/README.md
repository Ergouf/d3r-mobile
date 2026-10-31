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
python tools/d3-re/build_main_elf.py main.bin --out out/windows/kbm/b0/d3_main_fixed.elf
```

The `hactool --uncompressed` image keeps the NSO0 header, and each segment's
file offset is normally its memory offset plus 0x100. The script parses the
header and places `.text` / `.rodata` / `.data` / `.bss` at their **memory**
offsets, so a Ghidra address is the module-relative offset:

```text
Ghidra address = absolute guest address - 0x8005000
```

The older `d3_main.elf` (built without stripping the header) was shifted by
0x100; use `d3_main_fixed.elf` for all new analysis.

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
  -Elf .\out\windows\kbm\b0\d3_main_fixed.elf `
  -GhidraHome C:\tools\ghidra_12.1.4_PUBLIC `
  -JavaHome C:\tools\jdk-21
```

The B0 acceptance is the Frida probe plus the ELF; the Ghidra run is the B1
input. Do not treat a partial Ghidra analysis as evidence of absence.

## 5. B1b runtime probes

All probes are read-only; they spawn a throwaway game unless `--pid` is given.

Dump the Console UI callback table:

```powershell
python tools/d3-re/dump_ui_table.py --json out/windows/kbm/b1/ui_table.json
```

Dump another 24-byte-entry table (for example the transient PC UI table seen at
module offset `0x1874720`):

```powershell
python tools/d3-re/dump_ui_table.py --table-offset 0x1874720 --game-script "5000:1,15000:1,25000:1,35000:1,45000:400" --spawn-wait 55
```

Dump the Power script-function table from the fixed ELF:

```powershell
python tools/d3-re/dump_script_table.py --filter Cursor
```

Hook guest functions and post a key through the game window:

```powershell
python tools/d3-re/trace_ui.py --guest 0x81fb910 --key space
```

Watch inventory handlers while the game loads:

```powershell
python tools\d3-re\probe_inventory.py --seconds 58 --post-at 48
```

Resolve a guest address through `CPU.disp` (AOT/JIT host function) and inspect
`CPU.mem`:

```powershell
python tools\d3-re\find_cpu.py --guest 0x8366870 --guest 0x81fb910
```

Notes:

- UI handlers in the tables commonly point into a function, not to its entry;
  `DumpAt.java` prints the containing function when possible.
- `PostMessage(WM_KEYDOWN/UP)` works even when the game window is not focused.
- `CPU.mem + absolute_guest_address` reads guest memory; module-relative
  addresses must be offset by `0x8005000`.


## Safety

- No save writes, no `_code.dll` patches.
- Spawned probes are killed after reading unless `--keep` is given.
- All binary work products stay under `out/` (git-ignored).
