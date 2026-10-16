# Diablo 3 Android Compatibility Layer

Top-level pointer for this workspace. The actual project lives in
`d3-android/`; see `d3-android/README.md` and `d3-android/RECOVERY.md` for the
current state and `HANDOFF.md` for the (partly superseded) historical notes.

## Code checkpoint: 325fcdd (2026-10-16)

- Branch `recovery/d3host-sources`. Strict build of all five artifacts passes;
  the three Android-native suites PASS on the tablet; the 9 Python extraction
  tests PASS. This commits HIPC descriptor counting with raw/domain boundary
  validation and drops the whole-buffer SFCI scan.
- The game is **NOT runnable** (no `gameMainLoop` evidence). `/sdcard/D3/RomFS`
  is missing and boot stops at an assertion in the guest `main DT_INIT`; the
  current blocker is the unimplemented `set` command 5
  (`GetAvailableLanguageCodes2`), not the descriptor parser.
- `0f973c2` is the earlier close checkpoint (domain-close without a CMIF
  payload).

## Source set (the only correct files)

- `d3-android/host/d3_host.c`, `d3-android/host/d3_service.c`,
  `d3-android/host/d3_jni.c`.
- `d3-android/host/*_minimal.c`, `*_new.*`, `d3_table.c` and
  `jni_template.c` are uncompiled drift/stub artifacts - do not build them.

## Git / secrets

- Only project source, tests, tooling and docs are tracked. Local Git has no
  remote configured, so it is **not** an off-device backup.
- Game archives, extracted APKs, `.so` binaries, memory dumps and key material
  (for example `prod.keys`) are intentionally not tracked and must not be added.
