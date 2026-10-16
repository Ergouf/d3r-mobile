# d3-android - Diablo 3 Android Emulation Layer

Custom ARM64 emulation / IPC translation layer for running Diablo 3 on Android
through a translation layer. The main goal is a dedicated compatibility layer
plus APK wrapping - it is NOT an attempt to restore the game's own C++.

The active target and acceptance criteria are in [GOAL.md](GOAL.md); the current
stage is to move beyond `nnMain` on the real tablet without hiding failures.

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

## Current state (code stage 4b8f419, 2026-10-16)

Dated, not "latest forever" (later doc commits move the branch tip).

### Signal checkpoint `4b8f419` + `time` root/cmd3 (current)

- `4b8f419` ("preserve Android signal chain for non-guest threads") keeps the
  Android signal chain instead of intercepting ART-managed signals. Two real
  Activity-button starts (`signal-activity-01` pid 7201/7304, `signal-activity-03`
  pid 10072/10167) each reached `nnMain` with `markers[]`, the original APK
  SHA-256 `1659b8…95007e7` unchanged and no new crash; ART `sig11` and the 7 user
  threads no longer mix with kernel threads; each ran 20 samples (~40 s). This is
  a **bounded** fix: the guest thread's own ART **pre-handler risk stays open** —
  it does not prove all guest signals are safe.
- `time` root interface and cmd3 are implemented: root iface 22 → TZ iface 23
  child, domain data/error with `num_out_objects` 0 and factory 1, plus session
  and child-close lifecycle. `time-native02` PASSes all 7 native suites on device
  (the applet helper was changed to exact 0/1; no assertion skips).
- `time-activity-01` (real APK `f13d4332…97592`, host `c055a7eb…b0a4f7`, pid
  12088 / guest 12169) crossed cmd3 object 14 at 21:37:17. The next blocker is
  root cmd20 `GetSharedMemory` unsupported → `error 0x278` → `Break0` → a normal
  SIGABRT + debuggerd (post crash `b16f8330…e173`). That is a **new guest
  assertion**, not a recurrence of the old non-guest JIT fault, and
  **not** the app running.
- `d3_sync` (lock/unlock/wait/signal) PASSes 14 case kinds standalone on device.
  Scope: this is the startup-subset lock/unlock/process-wide-key implementation,
  **not** a full Horizon kernel; modules are FIFO, not priority-inheritance;
  `SVC 0x1B` is still the single-guest context tag 1; thread terminate/cancel and
  `WaitSynchronization` event semantics are not done, and the final tests pin only
  the implemented subset. The `0x1a..0x1d` success stubs are replaced, but the
  final SVC regression / ABI and latest-APK result are still to be collected —
  recorded as **pending**. Real `Create/Start` guest threads are still stubs.

### `4eb34b9` checkpoint (retained, still accurate)

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

- The game is not runnable; there is still no game loop.
- Real device `config-02` (`pid 32104` / guest `32139`) entered `nnMain` for the
  first time at 19:57:33; the old `main[160]` `ItemLock` SIGSEGV is **resolved**
  by the single-init fix, so treat that fault as historical, not current.
- **Superseded (historical, evidence kept)**: the old `time:u` rejection (`has no
  object 13`, iface 0) and the SVC `0x1c` stub loop were the `config-02` stage;
  the `time` root/cmd3 path is now implemented (see Current state). Likewise the
  old `fault pc=0x4804f37c`, `tid 32150 != guest 32139` (non-guest thread) and the
  `pid 32404` no-handler busy-loop comparison were that stage's phenomena, and the
  "raw host signal handler intercepts ART signals" was then a mere hypothesis.
  `4b8f419` addressed it (two real Activity starts, no new crash), but only
  **bounded**: the **guest thread's own ART pre-handler risk stays open**. Do not
  claim the app no longer crashes.
- Current next blocker (`time-activity-01`): after crossing cmd3 object 14, root
  cmd20 `GetSharedMemory` is unsupported → `error 0x278` → `Break0` → a normal
  SIGABRT + debuggerd. That is a **new guest assertion**, not a recurrence of the
  old non-guest JIT fault, and not app success.
- Guest threads Create/Start still only allocate a handle / return a success
  stub; real guest thread scheduling is not implemented.
- `/sdcard/D3/RomFS` is missing; graphics, audio, input and a deployable gameplay
  build are not done. A passing build and native tests are not running success.
- The guest binary cannot be rebuilt from Git: the source rewriter
  `build_guest_elf.py` is missing, so the preserved `libd3guest.so` is the only
  guest.
- Evidence (not in Git): `../recovery/d3host-20261016-huRwPN/analysis/`
  `signal-activity-01/`, `signal-activity-03/`, `time-activity-01/` (newest),
  plus the earlier `apk-config02-logcat.txt`, `apk-config02-crash.txt`,
  `apk-config02-default-handler.log`, `apk-config02-pid32404-full.log`,
  `apk-config02-default-handler.maps`, `apk-config02-default-handler-threads.log`.

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
- Latest real-device runs use `tools/verify_activity.py` against the real Activity
  button: `signal-activity-01` / `signal-activity-03` (signal, `4b8f419`) and
  `time-activity-01` (APK `f13d4332…97592`); earlier `config-02` first reached
  `nnMain`. The runner records commands, sha256 proofs and evidence; it does not
  install (the main session does `adb install -r` separately).
- Does NOT autostart by default; the button fires once (`Intent autostart=true`
  exercises the path for testing). A visible UI is not a working game: the process
  still exits after the guest starts. Evidence (not in Git):
  `.../analysis/signal-activity-01/`, `signal-activity-03/`, `time-activity-01/`,
  `apk-config02-logcat.txt`, `apk-config02-crash.txt`, `apk-config02-pid32104-full.log`.

## Offline packaging and tooling scope

- `tools/build_apk.py` packages and signs the debug APK from a freshly rebuilt
  host and the preserved guest; it requires both (`--host`, `--guest`) and never
  globs for a "latest" `.so`. `--keystore` reuses an existing local debug
  keystore across output directories (not tracked in Git).
- `build.sh`, `tools/build_host.py` and `tools/build_apk.py` only compile / build
  / package; they do not install or replace the installed APK. The actual
  `adb install -r` is a separate, explicitly authorized step. `tools/verify_activity.py`
  runs / captures evidence on the fixed recovery package only and never installs.

## Recovery artifacts and Git state

- Preserved APK: `../recovery/d3host-20261016-huRwPN/apk/base.apk`. Original
  binaries are excluded from Git (kept locally); no key material (APK / `.so` /
  memory dumps / keystore) is added to the repo.
- Branch `recovery/d3host-sources`, checkpoint `4b8f419` at this writing (tag
  `recovered-original-sources-20261016` marks the earlier `3e1c61c` checkpoint).
  No remote is configured, so local history is not an off-device backup.

See `RECOVERY.md` for the recovery checkpoint and `HANDOFF.md` for the
historical debugging notes (partly superseded).
