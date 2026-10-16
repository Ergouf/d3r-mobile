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
artifacts.

The pre-edit archival snapshots (2,260 / 1,100 lines) live under
`../recovery/d3host-20261016-huRwPN/source-candidates/`; those line counts
describe the archived originals, not the current working sources.

## Build

Run from `d3-android`:

    bash build.sh --build-tests

`build.sh` is a thin wrapper over `tools/build_host.py` (real Python 3.12,
absolute path, launched with `-I`) that sets `MSYS2_ARG_CONV_EXCL=*` so Android
paths reach native Python unchanged. To invoke the driver yourself, use the same
explicit Python 3.12 absolute path with `-I`; the bare `python3.12` Store alias
does not work.

`tools/build_host.py` flags:

- `--ndk` - NDK root (Windows path)
- `--output-dir` - output directory (Windows path)
- `--sandbox-root` - absolute Android path; sets `-DD3_DATA_ROOT`/`-DD3_PRIVATE_ROOT`
- `--build-probe` - also build `tools/d3_probe.c`
- `--build-tests` - compile-only; also build the native tests into `--output-dir`

Strict flags: `-Werror --no-undefined -ffixed-x18 -fno-stack-protector`. The
`Makefile` is now a thin wrapper over `build.sh`, but `make` is not available
here and has not been run - use `build.sh`.

## Verified checkpoint (code checkpoint 325fcdd, 2026-10-16)

Pinned to this code checkpoint, not "latest forever" (later doc commits move HEAD).

- `c25ab68` - complete JNI / build inputs; GetInfo 14/15 report the full 1 GiB
  stack allocation area (not just the occupied 8 MiB main stack) with
  `MapMemory`/`UnmapMemory` moving the real backing and protecting the source
  region; initial focus 15 delivered.
- `9fa57f9` - `ISelfController` command 16 (`SetOutOfFocusSuspendingEnabled`)
  tracked per object with bool low-byte normalization.
- `3d5d416` - the domain conversion returns allocated roots instead of the
  hardcoded object 1 (the earlier probe04 assert). Anti-loss check: a clean
  `git archive` of exactly `3d5d416` strict-builds all four artifacts
  (`libd3host.so`, `d3_probe`, `test_stack_memory`, `test_applet_focus`) with no
  missing inputs. This verifies build-input completeness only, not gameplay.
- `3d9dfe3` - models the pctl parental-control factories (commands 0/1) plus the
  child Initialize lifecycle.
- `c95cac0` - stops joining a detached guest startup thread (illegal
  `pthread_join` removed).
- `0f973c2` - prior close checkpoint: parses domain close requests that carry no
  CMIF payload (no SFCI magic) instead of rejecting them, and accepts only a
  genuine HIPC close 2/0 with an empty payload.
- `325fcdd` - the code checkpoint: counts HIPC descriptors (X/A/B/W) before
  locating the CMIF frame, validates the raw/domain data-size boundary, and
  removes the whole-buffer SFCI scan.

## Current state at code checkpoint 325fcdd

- Strict build of all five artifacts passes.
- Three Android-native suites PASS on the tablet: `test_stack_memory`,
  `test_applet_focus` and `test_hipc_message` (new; wired into the build
  driver). The test helper was also fixed to propagate `CHECK` results to
  `main` and to align the frame to an explicit 16 bytes; the suites re-passed on
  the tablet after that.
- The 9 Python extraction tests PASS (their sources did not change).
- Headers have been rebuilt and locally ABI-verified; this is not a full runtime
  verification of every path.
- A clean `git archive` of `325fcdd` strict-builds all five default artifacts and
  passes the nine Python extraction tests. This verifies tracked build inputs,
  not native execution of that archive build or gameplay.

## Limits (NOT proven, do not read as running)

- The game is not runnable and there is no `gameMainLoop` evidence.
- The isolated `boot-descriptor-02` probe loads and the async start returns 0,
  but the guest process exits on an assertion (exit 1), not the 20 s timeout. It
  reaches `back nninitStartup` and both `DT_INIT` (including `main`), succeeds at
  servicefileclose objects 14/13, and brings pctl object 12 to ready. It then
  issues a plain `set` command 5 with the correct magic `+0x20` and the request
  is handled as an unimplemented `set` cmd 5 (no longer misread as domain 28).
- Current blocker: `set` command 5 (`GetAvailableLanguageCodes2`) is not
  implemented - it is not a descriptor-parser problem.
- Guest threads Create/Start still only allocate a handle / return a success
  stub; real guest thread scheduling is not implemented.
- `/sdcard/D3/RomFS` is missing; graphics, audio, input and APK deployment are
  not done. Boot does not complete, so a passing build and native tests are not
  running success.

## Tooling scope

`tools/build_host.py` and `build.sh` only compile and build the device native
probe/tests. They do not install or replace the installed APK on the device, and
they never select stub sources or copy old headers.

## Recovery artifacts and Git state

- Preserved APK: `../recovery/d3host-20261016-huRwPN/apk/base.apk`
- Original binaries are excluded from Git (kept locally); no key material (APK /
  `.so` / memory dumps) is added to the repo.
- Branch `recovery/d3host-sources`, code checkpoint `325fcdd` (tag
  `recovered-original-sources-20261016` marks the earlier `3e1c61c` checkpoint).
  No remote is configured, so local history does not survive whole-disk loss and
  is not an off-device backup.

See `RECOVERY.md` for the recovery checkpoint and `HANDOFF.md` for the
historical debugging notes (partly superseded).
