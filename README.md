# Diablo 3 Android Compatibility Layer

Top-level pointer for this workspace. The actual project lives in
`d3-android/`; see [the current goal](d3-android/GOAL.md),
`d3-android/README.md` and `d3-android/RECOVERY.md` for the current state, and
`HANDOFF.md` for the (partly superseded) historical notes.

## Recent code stages (branch `recovery/d3host-sources`)

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
branch tip, so read the state below as of `4eb34b9`, not as "HEAD forever".

## Current state (code stage 4eb34b9, 2026-10-16)

- Strict NDK build of all seven artifacts passes: `libd3host.so`, `d3_probe` and
  the five native tests.
- Five Android-native suites PASS on tablet `R52T90127WT`: `test_stack_memory`,
  `test_applet_focus`, `test_hipc_message`, `test_set_service` and
  `test_boot_sequence` (new, synthetic guest 107 / 360 constructor counts). Built
  from the `6df9de6` snapshot the same test fails red (exit 1 at the
  `sdk_ctor_calls` assert), which pins the fix.
- A clean `git archive` of `4eb34b9` strict-builds the seven native artifacts and
  passes the nine Python tests, and packages + signs an APK with an externally
  preserved `libd3guest.so` and the existing debug key (`apksigner verify` PASS).
  This verifies tracked source / packaging inputs only; the archive artifacts were
  not run on a device, and the guest binary and key are not Git inputs.
- The old `main[160]` `ItemLock` fault is **resolved**. On device (`config-02`)
  the guest now reaches `nnMain` for the first time. It then sends `time:u`
  `ConvertCurrentObjectToDomain` for object 13 (iface 0) and the following
  request cmd3 is rejected (`has no object 13`), with an SVC `0x1c` loop (still a
  stub). Root cause of that rejection is not yet fixed. There is still no game
  loop.
- The game is still **NOT runnable** and the app has not stopped crashing: the
  process later exits, and the current crash has `fault pc=0x4804f37c`,
  `tid 32150 != guest 32139` (a non-guest thread), with an undetermined root
  cause. A no-handler diagnostic run (existing marker, no source change) also
  reached `nnMain` and stayed alive in a busy SVC `0x1c` stub loop until a forced
  stop; its maps show `0x48000000-0x4a000000` as a JIT-cache RX range (the same
  range as the earlier non-guest fault PC, though a different pid). The raw host
  signal handler intercepting ART-managed signals is suspected but not proven.
  `/sdcard/D3/RomFS` is missing, and graphics, audio, input and real guest thread
  scheduling are not done. Do not read the `nnMain` entry or a visible APK UI as
  "the game runs / no crash".

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
