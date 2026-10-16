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

## State at code checkpoint 3595280 (2026-10-16)

Dated milestone, not "latest forever" (later doc commits move the branch tip).

- Strict NDK build of all six artifacts passes with `--build-probe --build-tests`:
  `libd3host.so`, `d3_probe`, `test_stack_memory`, `test_applet_focus`,
  `test_hipc_message`, `test_set_service`.
- Four Android-native suites PASS on tablet `R52T90127WT` after being pushed and
  run on-device (including the new `test_set_service`, wired into the build
  driver). The test helper also propagates `CHECK` results to `main` and aligns
  the frame to an explicit 16 bytes.
- The 9 Python extraction tests PASS (their sources did not change).
- A clean `git archive` of `3595280` strict-builds the six native artifacts and
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

- The game is not runnable and there is no `gameMainLoop` evidence.
- Boot moves past `back nninitStartup`, both `DT_INIT` (including `main`) and
  into the `main` init array (count 360), reaching index 160; it then hits a
  guest SIGSEGV at `sdk+0x4db690` (strcmp) with caller `main+0x1a26b74`
  (`x1 = -0x48`). The suspected site is the `ItemLockCooldownMinutes` register
  loop whose linked-list `next` is 0; root cause is still under analysis - do not
  assert it is TLS or a missing RomFS.
- Guest threads Create/Start still only allocate a handle / return a success
  stub; real guest thread scheduling is not implemented.
- `/sdcard/D3/RomFS` is missing; graphics, audio, input and a deployable gameplay
  build are not done. Boot does not complete, so a passing build and native tests are not
  running success.

## Recovery APK diagnostic shell (package `com.d3mobile.host.recovery`)

- Fixed package name, separate from the original `com.d3mobile.host`, so it never
  overwrites the original APK (kept at SHA-256
  `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`); the
  original's own `g_table` crash is a distinct, still-open issue. Installed on the
  tablet (UID 10272) and launched via the Activity and a manual button tap
  (`pid 29429`). The new host library loads with `System.loadLibrary`, and the
  guest (33,227,200 bytes) comes from the original APK. Internal runtime root
  `/data/user/0/com.d3mobile.host.recovery/files/runtime`; private root
  `/data/user/0/com.d3mobile.host.recovery`.
- Diagnostic UI fixed on Android 16 (target 36): NoActionBar theme, WindowInsets
  handling and dark status-bar icons; screenshot
  `../recovery/d3host-20261016-huRwPN/analysis/apk-recovery-ui-03.png`.
- Does NOT autostart by default; the button fires once (`Intent autostart=true`
  exercises the path for testing). A visible UI is not a working game: launching
  the guest still ends the process, so it is not yet a "no crash" result. Evidence
  logs (not in Git): `.../analysis/apk-recovery-02-pid27088.log`,
  `apk-recovery-02-service.log`, `apk-recovery-manualtap-01*.log`.

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
