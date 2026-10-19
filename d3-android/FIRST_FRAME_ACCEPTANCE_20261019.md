# Android first-frame acceptance — 2026-10-19

## Result

The requested milestone is verified: the recovery Activity starts the original
Diablo III ARM64 guest on SM-X700, renders a legible real title screen, and
presents it through the Android SurfaceView. Two independent launches of the
installed coherent3 build reproduce it with no diagnostic marker or self-test.
The later attract/intro sequence also produces an actual cinematic image.

This accepts normal startup through the first real game screen, not the wider
project's playable-game objective. Input, audio, gameplay, complete kernel/service
compatibility, surface recreation and long-session stability are not accepted.

## Requirement audit

| Requirement | Authoritative evidence |
| --- | --- |
| Start on actual Android hardware | R52T90127WT / SM-X700; com.d3mobile.host.recovery Activity; coherent3 PID 29275 and replay PID 29516 |
| Execute the real guest and GPU work | Original guest SHA256 below; real GPFIFO submissions, syncpoint guest/host values, nvmap and guest QueueBuffer in gpu-coherent3*.txt |
| Correct first game image, not a clear/gradient | screenshot-coherent3-now.png and screenshot-coherent3-replay-2.png show the legible Diablo III Eternal Collection title, Press Any Button, Blizzard and actual background |
| Present to the display | Full-device screencaps plus surface-name-coherent3-replay.txt and nonzero SurfaceFlinger timestamps in surface-latency-coherent3-replay.txt |
| Repeatable normal configuration | Both launches use the same installed coherent3 APK; runtime contains only logs/ and saves/, no cache-scan/self-test/trace marker; both probes alive without AbortImpl or wild jumps |
| Regression checks | Fifteen suites exit 0 in build/native-coherent3-tests-results.txt; sources rebuilt in native-coherent3-tests-build.txt; standalone tracker also built through --build-gpu-tests |
| Preserve evidence and build identity | APK manifest, PID-filtered logs, screenshots, exit-info, surface timestamps and hashes listed below |

All probe names below refer to files under `gpu/probe/` unless another directory
is stated. `coherent3` captures 85 seconds; replay captures 90 seconds. Startup
resource-loading time varies with device memory/CPU load. Some timed screenshots
were taken before real rendering began and are black; they are not substituted
for the verified title-screen screenshots.

## Root cause and fixes

The GPU port's RasterizerMarkRegionCached and GatherGPUDirtyMemory were empty.
The renderer uploaded guest buffers once but missed subsequent CPU writes, so
UI vertices/uniforms remained stale and the logo/text stretched or disappeared.
An opt-in tracked-page scan first restored a correct title screen (cachescan1).
The normal configuration now enables CPU-write tracking by default.

`gpu/host/cpu_write_tracker.h` retains exact 4096-byte cached-page snapshots,
compares actual contents rather than probabilistic hashes, and reports changed
pages through canonical device addresses. Uncache removes the snapshot; repeated
cache notifications preserve the old snapshot. Collection callbacks run outside
the tracker mutex. This is a conservative coherence implementation, not NCE page
protection, and has memory/CPU costs and incomplete CPU readback semantics.

The first correct-image implementation rescanned approximately 19,000 pages at
every GPU cache barrier, making the GPU emulation thread CPU-bound. It now scans
once per CPU submission generation; subsequent barriers without another CPU
submission skip the repeated scan. Device-mapping invalidation still receives
the actually changed pages. Full coherent3 cache scans initially cost about
11–16 ms, so further performance work remains possible.

The inherited two-composite workaround duplicated each game frame, imposing
another presentation interval. The actual game path now requests one composite
and waits for its execution; the next real frame supplies ongoing renderer work.
This is verified with real surface timestamps, not just enqueue counts. The
standalone gradient self-test is not the normal startup path and remains off.

## Frame-rate measurement

Rates count real `guest-present: composited` log events after rendering starts,
not Android UI refresh rate or duplicated swapchain presents. These are title/
startup measurements, not gameplay benchmarks. Data is preserved in
`build/coherency-fps-comparison.json`.

| Build/run | Frames | Measured span | Mean FPS | Median / p95 frame interval |
| --- | ---: | ---: | ---: | --- |
| coherent1, scan every barrier | 133 | 39.793 s | 3.32 | 307.5 / 328 ms |
| coherent2, one scan/submission | 783 | 33.375 s | 23.43 | 44 / 52 ms |
| coherent2 replay | 1289 | 52.445 s | 24.56 | 39 / 52 ms |
| coherent3, one actual composite | 2519 | 50.489 s | 49.87 | 20 / 23 ms |
| coherent3 replay | 2728 | 55.307 s | 49.31 | 20 / 24 ms |

## Verified artifacts

- Installed APK: `build/apk-gpu-coherent3/d3host-recovery-debug.apk`
  SHA256 `7e8133c92820bbd1c9a4d0900c587907e5e054ecdc5b25f8fccece48f0492294`.
- Host SHA256 `bc14b1c8f4618f01958cb29bebbefa638fecdeed7f2f2f0acb3b94575cb98155`.
- Original guest unchanged:
  `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`.
- `screenshot-coherent3-replay-2.png` title screenshot SHA256:
  `72861dbfae171e4d660747c2740376ac60ab9a5582b5cd8746312a2b5eaa4872`.
- `screenshot-coherent3-now.png`: separate launch, correct title.
- `screenshot-coherent3-replay-late.png`: actual later cinematic image, not an
  indefinitely stuck black screen. This does not accept all video codecs.
- `gpu-coherent3.txt`, `gpu-coherent3-replay.txt`, matching `logcat-*`,
  `exit-info-*`; `gpu-coherent3-replay-first.txt` and `-late.txt`.
  The empty crash-buffer capture is recorded explicitly in
  `crash-buffer-coherent3-acceptance.txt`; no native tombstone is emitted.
- First replay recorded guest composite: 12:33:24.872, PID 29516, render TID
  29685, 1600x900 stride 1600, nvmap26, CPU0x555c080000/device0x48087000.
- `surface-latency-coherent3-replay.txt`: 16,666,666 ns display period and real
  presentation timestamps (not a claim of 60 game FPS).
- `build/native-coherent3-tests-{build,results}.txt`: fourteen host suites plus
  the CPU write tracker suite. All fifteen pass on-device. Tracker tests cover
  unchanged data, exact changed bytes, page boundaries, repeated caching,
  uncache/re-cache, invalid pointer registration and reentrant collection.

The existing all-tests command still encounters pre-existing stale stack-memory
test signatures; the fourteen supported host suites are rebuilt explicitly.
The new GPU regression is reproducible with build_host.py --with-gpu
--build-gpu-tests and the existing recovery runtime path options.

No app data cleared, uninstall, commits, pushes, branches or reference/Eden
modifications. All installs used `adb install -r`; every probe used `-Keep`.
Historical investigation and resource audit: FIRST_FRAME_BRINGUP_20261019.md.
