# Diablo 3 Android Compatibility Layer

Top-level pointer for this workspace. The actual project lives in
`d3-android/`; see `d3-android/README.md` and `d3-android/RECOVERY.md` for the
current state and `HANDOFF.md` for the (partly superseded) historical notes.

## Recent code stages (branch `recovery/d3host-sources`)

- `ab074d3` - the `set` service (HOS settings) serves cmd5
  (`GetAvailableLanguageCodes2`) through bounded buffers; the plain `set` cmd5
  reached during boot is now handled instead of being treated as unimplemented.
- `3595280` - isolated recovery APK diagnostic shell
  (`com.d3mobile.host.recovery`).
- `325fcdd` - HIPC descriptor counting with raw/domain boundary validation.
- `0f973c2` - earlier close checkpoint (domain-close without a CMIF payload).

These are dated milestones, not a permanent "latest": later docs commits move the
branch tip, so read the state below as of `3595280`, not as "HEAD forever".

## State at checkpoint 3595280

- Strict NDK build of all six artifacts passes: `libd3host.so`, `d3_probe` and
  the four native tests.
- Four Android-native suites PASS on tablet `R52T90127WT`: `test_stack_memory`,
  `test_applet_focus`, `test_hipc_message`, `test_set_service`.
- The 9 Python extraction tests PASS.
- The game is **NOT runnable**. Boot moves through `back nninitStartup`, both
  `DT_INIT` (including `main`) and the start of the `main` init array (count
  360), but stops at index 160 with a guest SIGSEGV at `sdk+0x4db690` (strcmp),
  caller `main+0x1a26b74`. Root cause still under analysis - do not assert it is
  TLS or a missing RomFS. `/sdcard/D3/RomFS` is missing, and graphics, audio,
  input and real guest thread scheduling are not done. A new APK with a visible
  UI does not mean a working game screen.

## Offline APK packaging (fixed package, does not overwrite the original app)

The recovery package is fixed to `com.d3mobile.host.recovery`, a separate package
from the original `com.d3mobile.host`, so installing it never replaces the
original (whose own `g_table` crash remains a distinct issue). The build tools
never install; `adb install -r` is a separate step done with explicit device
authorization.

Build host + probe + the four native tests (paths relative to the repo root):

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/set-03 --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --build-probe --build-tests
```

Package and sign with the real Python 3.12 absolute path, reusing the existing
local debug keystore (do not delete it or clear app data; reusing it keeps updates
compatible, and it is not tracked in Git):

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py --host d3-android/build/set-03/libd3host.so --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --keystore d3-android/build/apk-recovery-set02/local-debug.keystore --output-dir d3-android/build/apk-recovery-set04
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
