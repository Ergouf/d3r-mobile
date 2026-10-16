# d3-android - Diablo 3 Android Emulation Layer

Custom ARM64 emulation / IPC translation layer for running Diablo 3 on Android
through a translation layer. The main goal is a dedicated compatibility layer
plus APK wrapping - it is NOT an attempt to restore the game's own C++.

## Source set (the only correct files)

- `host/d3_host.c` - ARM64 instruction handling, signal handlers
- `host/d3_service.c` - IPC service call handlers
- `host/d3_jni.c` - JNI entry points

Missing headers were reconstructed from the C sources, guestbridge, and the
binary. The original host uses a `static` `g_table` pointer for the shared
host/guest table; there is no external `d3_table.c`.

Do NOT build with `host/d3_table.c`, `host/d3_host_minimal.c`,
`host/d3_service_minimal.c`, `host/d3_service_new.h`, `host/d3_table_new.c`,
`host/guest_layout_new.h`, or `host/jni_template.c` - these are drift/stub
artifacts. The pre-edit archival snapshots (2,260 / 1,100 lines) live under
`../recovery/d3host-20261016-huRwPN/source-candidates/`; those line counts
describe the archived originals, not the current working sources.

## Build

Run from `d3-android`: `bash build.sh --build-tests`.

`build.sh` is a thin wrapper over `tools/build_host.py` (real Python 3.12,
absolute path, launched with `-I`) that sets `MSYS2_ARG_CONV_EXCL=*` so Android
paths reach native Python unchanged. To invoke the driver yourself, use the same
explicit Python 3.12 absolute path with `-I`; the bare `python3.12` Store alias
does not work.

`tools/build_host.py` flags: `--ndk`, `--output-dir` (Windows paths),
`--sandbox-root` (absolute Android path; sets `-DD3_DATA_ROOT`/`-DD3_PRIVATE_ROOT`),
`--data-root`, `--private-root`, `--build-probe` and `--build-tests` (compile-only;
also builds the native tests into `--output-dir`). `--sandbox-root` is mutually
exclusive with `--data-root`/`--private-root`. Strict flags:
`-Werror --no-undefined -ffixed-x18 -fno-stack-protector`. The `Makefile` is now a
thin wrapper over `build.sh`, but `make` is not available here and has not been
run - use `build.sh`.

## Current state (code stage 4eb34b9, 2026-10-16)

Dated, not "latest forever" (later doc commits move the branch tip).

- Single-initialization fix (`4eb34b9`, "execute guest module constructors only
  once"; root cause located). The SDK and `main` `DT_INIT` already traverse their
  own full init arrays (`[0xc4bc88, 0xc4bfe0)` = 107 entries,
  `[0x215bed0, 0x215ca10)` = 360 entries), but the host also ran them a second
  time via `call_array`; that redundant pass is removed, leaving only the two
  `DT_INIT`. On `6df9de6` the double traversal re-cleared the `ItemLock` object's
  link, producing the old `main[160]` SIGSEGV at `sdk+0x4db690`; real-device
  `config-01` memory showed the list head already pointing at the `ItemLock`
  object, so it was not missing data or a guest empty map.
- Strict NDK build of all seven artifacts passes with `--build-probe
  --build-tests`: `libd3host.so`, `d3_probe` and the five native tests.
- Five Android-native suites PASS on tablet `R52T90127WT` (`config-02`):
  `test_stack_memory`, `test_applet_focus`, `test_hipc_message`,
  `test_set_service` and `test_boot_sequence` (new). Built from the `6df9de6`
  snapshot the same `test_boot_sequence` fails red (exit 1 at the
  `sdk_ctor_calls` assert), pinning the fix. The test helper also propagates
  `CHECK` results to `main` and aligns the frame to an explicit 16 bytes.
- The 9 Python extraction tests PASS.
- A clean `git archive` of `4eb34b9` strict-builds the seven native artifacts,
  passes the nine Python tests, and packages + signs an APK with an externally
  preserved `libd3guest.so` and the existing debug key (`apksigner verify`
  PASS). This verifies tracked source / packaging inputs only: the archive
  artifacts were not run on a device, and the guest binary and key are not Git
  inputs.

### `set` service (from `ab074d3`)

- Modern `set` cmd5 (`GetAvailableLanguageCodes2`) serves an 18-code language
  table (`en-US` at index 1) through a bounded HIPC buffer carrying the full
  22-bit address-high / 36-bit size fields, written with a bounded
  `process_vm_writev` self-copy; a legal 4-byte, byte-aligned output succeeds.
- The old cmd1 `OutPointer` path is still unsupported (0..6 is not complete).
  Scalar commands 0, 2, 3, 4 and 6 are implemented; region USA is 1; invalid
  enum values are rejected across the full u32 range.

### Earlier checkpoints (one line each)

- `325fcdd` - counts HIPC descriptors (X/A/B/W) before the CMIF frame, validates
  the raw/domain size boundary, drops the whole-buffer SFCI scan. `0f973c2` -
  parses domain close with no CMIF payload; only a genuine empty HIPC close 2/0.
- `c95cac0` / `3d9dfe3` - no longer joins a detached guest startup thread; models
  the pctl parental-control factories (0/1) and child Initialize lifecycle.
- `c25ab68` / `9fa57f9` / `3d5d416` - full 1 GiB stack area in GetInfo 14/15 with
  real `MapMemory`/`UnmapMemory` backing and initial focus 15; per-object
  `ISelfController` cmd 16; domain conversion returns allocated roots.

## Limits (NOT proven, do not read as running)

- The game is not runnable.
- Real device `config-02` (`pid 32104` / guest `32139`) entered `nnMain` for the
  first time at 19:57:33 - the old `main[160]` `ItemLock` SIGSEGV is **resolved**
  by the single-init fix above, so treat that fault as historical, not current.
- It then sends `time:u` `ConvertCurrentObjectToDomain` for object 13 (iface 0),
  and the following request cmd3 is rejected (`has no object 13`), with an
  SVC `0x1c` loop (still a stub). That rejection has no fix yet.
- The process later exits; the current crash is `fault pc=0x4804f37c`,
  `tid 32150 != guest 32139` (a non-guest thread), and its root cause is not yet
  determined. A no-handler diagnostic run (`pid 32404` / guest `32429`, existing
  marker, no source change) also reached `nnMain`, stayed alive in a busy SVC
  `0x1c` stub loop, and was force-stopped after ~60 s CPU; its maps show
  `0x48000000-0x4a000000` as a JIT-cache RX range. That range matches the earlier
  non-guest fault PC (different pid, so not positively the same mapping), which
  raises the suspicion that the raw host signal handler is intercepting
  ART-managed signals - suspected, not fixed or proven. Do not read the `nnMain`
  entry as "the game runs / does not crash"; there is still no game loop.
- Guest threads Create/Start still only allocate a handle / return a success
  stub; real guest thread scheduling is not implemented.
- `/sdcard/D3/RomFS` is missing; graphics, audio, input and a deployable gameplay
  build are not done. A passing build and native tests are not running success.
- Evidence (not in Git): `../recovery/d3host-20261016-huRwPN/analysis/apk-config02-logcat.txt`
  (nnMain at lines 833..838; time:u / cmd3 / SVC 0x1c at 855..913),
  `apk-config02-crash.txt`, `apk-config02-default-handler.log`,
  `apk-config02-pid32404-full.log`, `apk-config02-default-handler.maps`,
  `apk-config02-default-handler-threads.log`.

## Recovery APK diagnostic shell (package `com.d3mobile.host.recovery`)

- Fixed package name, separate from the original `com.d3mobile.host`, so it never
  overwrites the original APK (kept at SHA-256
  `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`, verified
  unchanged again this round); the original's own `g_table` crash is a distinct,
  still-open issue. Installed on the tablet (UID 10272) and launched via the
  Activity. The new host library loads with `System.loadLibrary`, and the guest
  (33,227,200 bytes) comes from the original APK. Internal runtime root
  `/data/user/0/com.d3mobile.host.recovery/files/runtime`; private root
  `/data/user/0/com.d3mobile.host.recovery`.
- Diagnostic UI fixed on Android 16 (target 36): NoActionBar theme, WindowInsets
  handling and dark status-bar icons; screenshot
  `../recovery/d3host-20261016-huRwPN/analysis/apk-recovery-ui-03.png`.
- Latest run `config-02` reuses the existing key to update the APK (see Limits for
  the `nnMain` result).
- Does NOT autostart by default; the button fires once (`Intent autostart=true`
  exercises the path for testing). A visible UI is not a working game: the process
  still exits after the guest starts. Evidence (not in Git):
  `.../analysis/apk-config02-logcat.txt`, `apk-config02-crash.txt`,
  `apk-config02-pid32104-full.log`.

## Offline packaging and tooling scope

- `tools/build_apk.py` packages and signs the debug APK from a freshly rebuilt
  host and the preserved guest; it requires both (`--host`, `--guest`) and never
  globs for a "latest" `.so`. `--keystore` reuses an existing local debug
  keystore across output directories (not tracked in Git).
- `build.sh`, `tools/build_host.py` and `tools/build_apk.py` only compile / build
  / package; they do not install or replace the installed APK. The actual
  `adb install -r` is a separate, explicitly authorized step.

## Recovery artifacts and Git state

- Preserved APK: `../recovery/d3host-20261016-huRwPN/apk/base.apk`. Original
  binaries are excluded from Git (kept locally); no key material (APK / `.so` /
  memory dumps / keystore) is added to the repo.
- Branch `recovery/d3host-sources`, checkpoint `3595280` at this writing (tag
  `recovered-original-sources-20261016` marks the earlier `3e1c61c` checkpoint).
  No remote is configured, so local history is not an off-device backup.

See `RECOVERY.md` for the recovery checkpoint and `HANDOFF.md` for the
historical debugging notes (partly superseded).
