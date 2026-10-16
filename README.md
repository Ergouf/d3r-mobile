# Diablo 3 Android Compatibility Layer

Top-level pointer for this workspace. The actual project lives in
`d3-android/`; see [the current goal](d3-android/GOAL.md),
`d3-android/README.md` and `d3-android/RECOVERY.md` for the current state, and
`HANDOFF.md` for the (partly superseded) historical notes.

## Recent code stages (branch `recovery/d3host-sources`)

- `4b8f419` - "preserve Android signal chain for non-guest threads" (signal
  checkpoint): the host keeps the Android signal chain instead of intercepting
  ART-managed signals. Two real Activity-button starts reached `nnMain` with no
  new crash and the original APK unchanged, but this is bounded - the guest
  thread's own ART pre-handler risk stays open.
- `4eb34b9` - "execute guest module constructors only once" (single-init fix;
  root cause located): the SDK and `main` `DT_INIT` already traverse their own
  full init arrays, but the host also ran the arrays a second time via
  `call_array`; that redundant pass is removed so only the two `DT_INIT` remain.
  On `6df9de6` the double traversal re-cleared the `ItemLock` object's link,
  which was the old `main[160]` SIGSEGV; on real device `config-01` memory showed
  the list head already pointing at the object, so it was not missing data or an
  empty guest map.
- `ab074d3` - the `set` service (HOS settings) serves cmd5
  (`GetAvailableLanguageCodes2`) through bounded buffers.
- `3595280` - isolated recovery APK diagnostic shell
  (`com.d3mobile.host.recovery`).
- `325fcdd` - HIPC descriptor counting with raw/domain boundary validation.
- `0f973c2` - earlier close checkpoint (domain-close without a CMIF payload).

These are dated milestones, not a permanent "latest": later docs commits move the
branch tip, so read the state below as of `4b8f419`, not as "HEAD forever".

## Current state (code stage 4b8f419, 2026-10-16)

- `4b8f419` signal checkpoint: the host preserves the Android signal chain.
  Real Activity-button starts `signal-activity-01` (pid 7201/7304) and
  `signal-activity-03` (pid 10072/10167) reached `nnMain` with `markers[]`, the
  original APK SHA-256 unchanged, and no new crash; ART `sig11` and the 7 user
  threads no longer mix with kernel threads. Bounded: the guest thread's own ART
  **pre-handler risk stays open**.
- `time` root interface and cmd3 are implemented (root iface 22 → TZ iface 23
  child, domain `num_out_objects` 0 / factory 1, session + child-close lifecycle).
  `time-native02` PASSes all 7 native suites on device. `d3_sync`
  (lock/unlock/wait/signal) passes 14 case kinds standalone - a startup-subset
  implementation (FIFO, `SVC 0x1B` still single-guest tag 1), not a full Horizon
  kernel; the `0x1a..0x1d` stubs are replaced but the final SVC regression / ABI
  is **pending** and real `Create/Start` threads are still stubs.
- `time-activity-01` (real APK `f13d4332…97592`, host `c055a7eb…b0a4f7`, pid
  12088 / guest 12169) crossed cmd3 object 14 at 21:37:17; the next blocker is
  root cmd20 `GetSharedMemory` unsupported → `error 0x278` → `Break0` → a normal
  SIGABRT + debuggerd. That is a **new guest assertion**, not a recurrence of the
  old non-guest JIT fault, and not app success.
- Historical `4eb34b9`: strict NDK build of the seven artifacts and five
  Android-native suites (incl. `test_boot_sequence`, which fails red on the
  `6df9de6` snapshot) plus the nine Python extraction tests PASS; a clean
  `git archive` strict-builds and packages/signs an APK from the preserved guest
  (tracked source / packaging inputs only - not device-run). The old `main[160]`
  `ItemLock` fault is **resolved**. The earlier `time:u` cmd3 rejection and the
  non-guest `fault pc=0x4804f37c` crash (with the "host raw signal handler
  intercepts ART signals" hypothesis) were the `config-02` stage and are
  **superseded** - kept as evidence, not as current state.
- The game is still **NOT runnable**: `/sdcard/D3/RomFS` is missing, and graphics,
  audio, input and real guest thread scheduling are not done. Do not read any
  `nnMain` entry or a visible APK UI as "the game runs / no crash".

## Offline APK packaging (fixed package, does not overwrite the original app)

The recovery package is fixed to `com.d3mobile.host.recovery`, a separate package
from the original `com.d3mobile.host`, so installing it never replaces the
original (whose own `g_table` crash remains a distinct issue; the original APK
SHA-256 `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7` was
verified unchanged again this round). The build tools never install;
`adb install -r` is a separate step done with explicit device authorization.

Build host + probe + the five native tests (paths relative to the repo root):

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/config-02 --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --build-probe --build-tests
```

Package and sign with the real Python 3.12 absolute path, reusing the existing
local debug keystore (do not delete it or clear app data; reusing it keeps updates
compatible, and it is not tracked in Git):

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py --host d3-android/build/config-02/libd3host.so --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --keystore d3-android/build/apk-recovery-set02/local-debug.keystore --output-dir d3-android/build/apk-recovery-config02
```

## Source set (the only correct files)

- `d3-android/host/d3_host.c`, `d3-android/host/d3_service.c`,
  `d3-android/host/d3_jni.c`.
- `d3-android/host/*_minimal.c`, `*_new.*`, `d3_table.c` and
  `jni_template.c` are uncompiled drift/stub artifacts - do not build them.

## Git / secrets

- Only project source, tests, tooling and docs are tracked. Local Git has no
  remote configured, so it is **not** an off-device backup.
- Game archives, extracted APKs, `.so` binaries (including the recovered
  `libd3guest.so`), memory dumps and key material (for example `prod.keys` and
  the debug keystore) are intentionally not tracked and must not be added.
