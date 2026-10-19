# Android first-frame bring-up — 2026-10-19

## Superseding acceptance

The correct first game screen is now verified in the default coherent3 build
and same-APK replay at about 49–50 FPS. CPU cached-write tracking fixes the
distorted logo/text; submission-generation scanning and one composite per frame
fix the ~3 FPS regression. The later replay also displays an actual cinematic.
Fifteen supported native suites pass. See `FIRST_FRAME_ACCEPTANCE_20261019.md`
for current evidence and exact scope. All remaining status sections here are
historical investigation, not the final acceptance state.

## Latest evidence — real game image, visual correctness still open

**Actual guest frames are visibly presented on Android. The goal remains active
because normal visual startup is not yet correct.** Blue-green stone-hall game
backgrounds appear in three independent launches; logo/text is severely
stretched/distorted, and later frames become mostly black with small gold blocks.
This is not a claim of pixel-correct title-screen rendering or playability.

### Reproduction and evidence

- Device SM-X700, serial R52T90127WT, recovery package only.
- `window6`: PID 21332, first recorded composite 09:40:13.378, real 1600x900,
  stride 1600, nvmap 26, guest CPU 0x555c080000, canonical device 0x48087000.
  `gpu/probe/screenshot-window6.png` contains real game scenery.
- `window7`: PID 22141, 105-second probe alive, still submitting/presenting over
  two minutes later. `gpu/probe/screenshot-window7.png` shows the same scene.
  `surface-latency-window7.txt` records nonzero Android frame timestamps.
- `window8`: PID 22488, 75-second probe alive, no AbortImpl/wild jumps.
- `window8-replay`: same installed APK, PID 23056. Timed screenshots at 25,
  30, 35, 40, 45 and 50 seconds after starting the capture helper; the helper
  starts after the probe reports PID, so these are not exact process ages.
  `gpu/probe/screenshot-window8-replay-40.png` has SHA256
  `14e89032c43d86d9faed5c885adfbf3beef8c58bc9c653994bfda0e69a877e1d`.
  `surface-latency-window8-replay.txt` provides real SurfaceFlinger presentation
  timestamps. Original full-device screenshots are retained, not replaced by
  composited or generated artwork.
- `gpu-window8.txt`, `gpu-window8-replay.txt`, matching PID-filtered logcat,
  exit-info and tombstone files are under `gpu/probe/`. Chatty HID diagnostics
  can overrun logcat's ring, so a late probe may miss startup or the earliest
  composite. `nvdrv::Ioctl#` is capped; absence in a rolled log is not no ioctls.

### Repairs in this continuation

1. Removed all six dummy VI construction hooks and the placeholder native-window
   arena. Original SDK CreateLayer, DeserializeNativeWindow and GetNativeWindow
   now run. VI returns a 60-byte parcel containing a native-window binder object
   with producer id 1 and service name dispdrv, rather than a fake event pointer.
2. Implemented Binder reference adjustment, native buffer-availability event,
   interface-token and parcel bounds validation, connect/disconnect/query,
   preallocated-buffer registration, dequeue, request, cancellation without a
   pending fence, and actual QueueBuffer presentation. Unsupported transactions
   return Android -38 rather than success. Scope is a single display/producer.
3. Nvmap presentation pins hold actual allocations until buffer replacement or
   disconnect. Framebuffer import/release owns a canonical device mapping.
   The same backing and contained ranges reuse one DAddr across GPU VA aliases
   and display import. Window5 allocated an independent display alias and showed
   black; window6 reuses the GPU's DAddr and displays the game background.
4. QueueBuffer passes actual guest format, stride, crop, transform and acquire
   fences. Host syncpoints are checked (5-second timeout, no invented fence
   completion), then real FramebufferConfig goes through RendererVulkan.
   Two composites currently drive the present callback/flush pipeline.
5. Fixed inherited diagnostic hook address: 0x532730 is NvOsRealloc's PLT.
   `_Unwind_RaiseException` actually starts at 0x531730. The mis-hook caused a
   false exception report from Parcel::continueWrite in window2. Original realloc
   and VI instructions are now regression-checked.
6. Corrected AOC CMIF command numbers, confirmed against original guest wrappers:
   count=2, list=3, base id=5, changed-event=8. Previously cmd2 allocated a fresh
   event on every count query, leaked handles and caused later aborts. A static
   no-installed-DLC list now returns count zero and an unsignaled copy event.

### Earlier resource/HID fixes (supersede the Particle blocker below)

Full SHA256 audit of all 23 device CPKs versus the existing update extraction
found only CoreCommon and ServerCommon mismatched (base version). The old files
were backed up to `recovery/resource-backup-20261019/` before staging verified
update versions; no resource was fabricated and no reference file was modified.

| Resource | Old SHA256 | Correct update SHA256 |
| --- | --- | --- |
| CoreCommon.cpk | 5f514d41df480de15fa7edf2bb85bf523a3893bcd8ae29163e0e0cf39486332b | 2117e7a9b3d966c6e90a89eec7e2c6b7b6d2fb73ae2cf0e7e24c65c4da33ce3b |
| ServerCommon.cpk | b97295fa1fb5128852597ef9dc3365d433b82925bceb7ac638fb6b316ed70f1f | dfd1930de7a38573a7366ab38e88047064f3226db86adc7771a59ec2099fc637 |

Particle cache diagnostic showed 21398 occupied resources, zero references,
flags 0xc5 on every resource and zero eligible eviction candidates. x20=0x5396
was the scan cursor, not SNO. Correct resource versions eliminated this assertion
without increasing limits. `cpkversion1` then exposed HID vibration validation:
active style3 was incorrectly both FullKey and Handheld. Npad0 is now FullKey1
only; original guest GetVibrationDeviceHandles returns two valid handles.
`npadstyle1` then exposed window NULL 0x43a02c, which the VI repair supersedes.

### Build and regression identity

- Installed `build/apk-gpu-window8/d3host-recovery-debug.apk`:
  SHA256 `af55a878f89daef84bff618df718602e578ba4e38ade0f7b2cd35e4fa69ede36`.
- Host SHA256 `495909f728d97dc273f1cbe303e667b7d55dae55be3febb5db4ecb9c80433589`.
- Guest unchanged: `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`.
- Fourteen native suites rebuilt from current source and passed on tablet:
  `build/native-window8-tests-{build,results}.txt`. Added VI parcel/reference,
  actual nvmap pin retention through guest Free, preallocate/dequeue/request/
  cancel/disconnect and malformed-parcel tests; AOC 1000-count no-handle-leak
  test; original realloc/VI instruction checks and original vibration test.
  The earlier window6 TLS run used a nonexistent guest filename; rerunning with
  `/data/local/tmp/d3-test-guest.so` passed, as does the full window8 run.
- Default all-tests build still stops on pre-existing test_stack_memory's stale
  on_tpidrro signature; the fourteen supported suites above are built explicitly.
- No commits, pushes, branches, app-data clearing, uninstall or reference edits.

### Remaining work / do not overclaim

Logo and text rendering is wrong. Later black frames are not proven a normal
loading transition. Diagnose actual render-target/texture/vertex/uniform content;
CPU/GPU dirty-memory tracking stubs are a plausible lead, not an established
cause. No need to restore the invalid VI arena or bypass game assertions.
Buffer-availability events model the single synchronous consumer; full Android
BufferQueue scheduling, asynchronous release fences, multi-display/layer state,
surface recreation and complete GPU retirement are not implemented. Unsupported
overlapping backing ranges are refused, not silently given incoherent aliases.
Input/audio remain incomplete and there is no gameplay acceptance.

## Historical records (superseded by evidence above)

## Acceptance and status

The objective remains an actual Diablo III guest frame rendered and presented
by the Android Activity, with reproducible logs and frame evidence. A clear,
gradient, mapped buffer, running process, or successful ioctl is not a game frame.

**M2 is now observed: real guest nvdrv ioctls execute. M3 is not achieved.**
The `nvdrv::Ioctl#` diagnostic is capped at 80, so its line count is a lower
bound, not the total number of ioctls. Actual GPFIFO submission is now observed
(nvsubmit1 and later); completed GPU execution and game presentation are not
yet established.

## Verified progress

- Address arbitration SVC 0x34/0x35 now implements actual predicates, waits,
  updates, timeout and wake-count semantics. This ends the controller-app loop.
- Guest hook and SVC bridges use the calling thread's own Android TP and x18.
  The SVC bridge preserves q8–q31 as well as the original veneer's q0–q7.
- Missing files return FS path-not-found 0x202. The original game existence
  callback runs instead of the old unconditional-success replacement. Host paths
  normalize the game's backslash separators.
- A directory-backed save-filesystem domain interface implements open, commit,
  capacity queries, entry type and close. Save identity now comes from a stable
  local offline UID rather than uninitialized guest output.
- A single-use preselected-user launch storage contains the 0x88-byte Horizon
  ABI, magic 0xc79497ca, selected flag and the same local UID. The real SDK opens
  its account manager; online availability returns an offline-account result.
- Removed both inherited account assertion bypasses. The patch at SDK 0x4c328
  returned without unwinding OpenPreselectedUser's 0x20-byte frame. This made the
  language selector return into callback-table data at guest offset 0x20abf80.
  Local BL/RET probes demonstrated the SP and FP change across this exact call.
- Plain nvdrv Open replies no longer include a domain header. This removes the
  repeated Open loop and exposes real GPU-characteristics and nvmap ioctls.
- `host/d3_nvdrv.c` implements GPU characteristics, TPC and zcull queries,
  per-session descriptors, nvmap create/allocate/query/duplicate/free,
  address-space initialization/regions/reservations and supported map/unmap.
  Unknown device paths and ioctls fail explicitly, not with empty success.
- Removed the inherited NV initialization hook that wrote a self-referencing
  placeholder into the guest device.
- Supported GPU mappings use Eden's actual device and GPU page tables. The
  bridge checks translated pointers against shared physical backing. Guest
  alias RAM uses shared HostMemory mappings, not copies. The backing reserve is
  8 GiB virtual/sparse physical backing, with a 64 GiB guest alias reservation;
  this does not mean 8 GiB of resident memory is committed.
- The Activity waits for renderer initialization before starting guest code and
  keeps its visible window awake. Solid-color, memory and gradient self-tests
  are opt-in via `files/runtime/gpu-self-test`, disabled during game probes.

## Latest artifacts

### Resource and service continuation (supersedes nvgpumap5 diagnosis)

- The signal entry now restores the interrupted thread's Android TP/x18 before
  calling host diagnostics. This exposed the real guest SIGILL assertion rather
  than a secondary ART SIGSEGV. `d3-crash-signalentry1-now.txt` records the
  Globals resource-manager failure.
- The update guest was missing its update resources on-device. All 14 existing
  legitimate update CPKs (3,485,566,612 bytes) are now staged under
  `/data/local/tmp/d3romfs/Update`. No substitute game content was generated.
- Open/read/count/close directory hooks implement Horizon's 0x310-byte entry ABI,
  directory/file filtering and cursor-preserving counts. The file table grew
  from 32 to 256 with synchronized allocation/close; 48 simultaneous handles
  are covered by `test_directory`.
- `logcat-updatecpk2-trace.txt` confirms later patches through Patch2_7_7 load,
  then exposed a NULL NIFM general-service object. The normal updatecpk2 capture
  is invalid because overlapping probes cleared its logs; do not use it.
- NIFM root factory commands 4/5 now return a general-service child. Its primary
  IP query and basic network predicates report the local offline configuration.
  `logcat-nifm1.txt` passes this point and aborts on PCTL child command 1001.
- PCTL 1001 is CheckFreeCommunicationPermission: the local profile has no
  configured parental restrictions, so it authorizes communication and records
  that state. This is independent of network connectivity. HIPC regression
  passes. `logcat-pctl1.txt` confirms two guest callers pass this check, then
  finds plain APM OpenSession and NIFM CreateRequest unimplemented.
- APM now returns a real plain session handle (or a domain child), maintains
  performance configuration preferences for the two guest modes, and reports
  normal mode with CPU overclock disabled. Android still controls real clocks.
- NIFM CreateRequest now returns an isolated offline request object with copied
  state/change events, configuration input, terminal offline result and no
  invented network connection. `logcat-apmnifm1-app-only.txt` confirms the guest
  reads its state and reaches `/dev/nvhost-gpu` Open, previously unsupported.
- The apmnifm1 raw log was captured unfiltered after a startup PID race and
  includes native-test logs. Only its PID 10368 filtered derivative is valid
  guest evidence (80 capped ioctl log lines, zero AbortImpl calls). Android
  exit-info records PID 10368 SIGSEGV at 08:25:22.690. Its copied crash dump is
  stale from pctl1 and must not be attributed to this run.
- The probe now waits for the recovery PID and refuses unfiltered capture,
  also collecting PID-filtered GPU logs and Android exit-info. All thirteen
  targeted suites were rebuilt and passed with the APM/NIFM changes.
- GPU channel allocation, AS binding and engine initialization are now connected
  to Eden behind the C ABI; nvhost-gpu descriptor/configuration/context/GPFIFO
  allocation regression passes. `gpu-nvnotify1.txt` confirms actual channel 1
  (bind 2) allocation, binding to guest AS 1 and engine initialization.
  Submission was still unsupported at nvchannel1; see the later update below. Channel
  retirement is retained until process teardown because Eden's GPU-level
  ReleaseChannel remains unimplemented. Address spaces cannot close while a
  live descriptor is bound; full in-flight lifecycle still needs work.
- `nvchannel1` then rejects SetErrorNotifier. The repair validates and pins the
  nvmap object, clears the actual 16-byte notification record, and releases its
  pin on disable/replacement/channel close. Native tests verify bounds and bytes.
- `nvnotify1` exposes the game's in/out time-slice encoding `0xc004481d`, now
  accepted alongside the write-only form. It also exposes MapBufferEx flag
  `0x100`: a kind-only remap of an existing mapping, not a new nvmap handle.
  The C layer validates the subrange; the C++ bridge updates the actual PTE kind
  while preserving its device backing. `gpu-nvkind1.txt` records these remaps.
- IApplicationFunctions NotifyRunning records the transition and returns a
  well-formed boolean. This is applet lifecycle state, not first-frame evidence.
- `nvkind1` (PID 11931) passes these interfaces, with no logged ioctl errors or
  AbortImpl call, then exits via SIGSEGV. `trace-nvkind1.txt` identifies the true
  fault at merged guest `0x3197f4`, nn::nfp::Initialize dereferencing a NULL
  child interface (TID 12309, fault address 0); a secondary ART fault follows.
- NFP now has a real manager/child interface, init/finalize/state and an empty
  NFC-device list. It does not invent amiibo data or NFC hardware. Targeted HIPC
  regression passes and nfp1 validates it on-device. Startup continues for about
  30 more seconds, then reaches a real Particle resource-management assertion.

### First actual guest submission and current blocker

- ZCullBind now validates its guest GPU mapping and records the per-channel
  culling context. `nvzcull1` exposes the first actual guest SubmitGpfifo ioctl:
  Ioctl2 `0xc018481b`, count 3, flags 0x104 (not yet implemented in that build).
- Ioctl2 now decodes its second directional input buffer as GPFIFO entries.
  The channel layer validates sizes/session/lifecycle, dispatches to Eden and
  returns the channel syncpoint's requested fence maximum without falsely
  marking execution complete. Wait/increment flags construct actual puller
  command lists; unsupported flags and invalid GPU spans return errors.
- `gpu-nvsubmit1.txt`: **08:44:36.719, PID 13733, bind 2, count 3**, real guest
  entries dispatched and submission returns successfully. The guest's ioctl
  reply is success with 24 input, 24 output and 24 inline-input bytes. This is
  not a game frame. `nvquiet1` and `cvowner1` reproduce the same submission.
- Immediate syncpoint snapshots in those later builds are guest=0, host=0;
  enqueue acceptance alone is not GPU completion proof. The later workers1
  snapshot proves execution (see below); no presentation is recorded.
- `d3-crash-nvsubmit1.txt`, `d3-crash-nvquiet1.txt` and `d3-crash-cvowner1.txt`
  show the same Particle resource assertion: PC 0x1a2c440 (intentional illegal
  instruction), caller 0x16c24b8, x20=0x5396. The diagnostic enumerates Particle
  resources. Older builds spend around 32 seconds after NotifyRunning before
  failing. Do not skip this assertion or change game limits as a "fix".
- Rate-limiting successful IPC stack dumps and read/poll diagnostics reduces
  captured lines from ~73,000 to ~8,700 but does not resolve this failure.
- Removed the inherited patch at 0x3499b0. Disassembly proves this is a
  condition-variable **lock ownership check**, not a NULL-object check. The
  normal guest still reaches GPFIFO submission with the check intact. Native
  guest regression verifies the original instruction survives load_guest.
- All fourteen native suites pass on current runtime/service code, including
  Ioctl2 input-only buffer preservation, submission fence bookkeeping and cull
  mapping validation (`build/native-cvowner1-{build,results}.txt`).
- An opt-in `files/runtime/sample-workers` marker enables delayed CPU sampling
  of guest workers after resource initialization and a later syncpoint snapshot.
  workers1 device validation completes with the same Particle assertion. Its
  marker is removed. It does not alter guest code or synthesize completion.
- `gpu-workers1.txt`: at **08:53:38.243, PID 15300**, syncpoint id 1 has
  **guest=1, host=1** after the initial zero snapshot. This confirms real GPU
  execution of the first submitted guest batch, not merely queue acceptance.
- `samples-workers1.txt` records all worker PCs at 50–54 seconds. Busy main,
  loader and network workers overwhelmingly sample in libc stdio read, while
  other workers sleep in futex. `sync_address_access` was reopening and parsing
  `/proc/self/maps` for every synchronization operation, with thousands of VMAs.
- An explicit opt-in-for-runtime permission cache now reuses successful mapping
  permissions, invalidated by heap, alias, stack and protection changes. The
  standalone synchronization API keeps uncached validation by default. Cache
  invalidation/protection regression, address arbitration and original guest
  TLS suites pass. synccache1 reaches submission in about 18 seconds from nnMain,
  versus about 42 seconds before caching, but still reaches the same assertion
  about 9 seconds later. This improves host overhead, not game correctness.
- cacheprofile1 reproduces the failure and supplies 21–25 second worker samples
  (`samples-cacheprofile1-now.txt`). Most workers sleep; main and loader execute
  allocator/lock paths. `trace-cacheprofile1.txt` preserves the assertion chain:
  0x16c24b8 -> 0x16c5b8c -> 0x16c69cc -> 0x16c6690 -> 0x16c911c -> 0x16c4048
  -> 0x1127560 -> 0x113c084 -> 0x113f978 -> 0x103cf3c -> 0x14c76f4.
- **Refined diagnosis:** 0x16c5b60 compares resource count at +0x10c with its
  limit at +0x100 and calls 0x16c1f90 to select an eviction candidate. If no
  candidate qualifies, it enumerates the resource table and asserts. x20 is a
  table scan cursor here, **not a proven desired SNO**; the previous wait-timeout
  interpretation was too strong. Diagnose resource limits/reference states and
  the requesting path instead of changing timeouts or fabricating resources.
- All fourteen suites were rebuilt and passed with the cache and current
  diagnostics (`build/native-cacheprofile1-{build,results}.txt`). All probes
  have finished; trace and sample-workers markers are removed.

Latest installed validated diagnostic build:
`build/apk-gpu-cacheprofile1/d3host-recovery-debug.apk`:

- APK SHA256: `0efe802c07c90455551fc52719d519c3bb08c8d2c37725cec6c3863dbe9ce0e6`
- Host SHA256: `44bc1a64e254312adacf985f9a43bd85f4bea72b123cd8ea67429b4466225a33`
- Guest remains `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`.

Last fully verified normal build: `build/apk-gpu-cvowner1/d3host-recovery-debug.apk`:

- APK SHA256: `4df296df8de2bb035ade002b53e96bb99179f256a17563a573b8d167e9ab32a0`
- Host SHA256: `00d385f54f86457ff4ae6bfaeaf32e9ad65ad91cad0f57fc63510c126636915c`
- Guest SHA256 remains unchanged. Latest installed diagnostic candidate is workers1.

Latest candidate: `build/apk-gpu-nfp1/d3host-recovery-debug.apk` (identity in its
adjacent JSON; validation pending). Last fully captured build is nvkind1:

- APK SHA256: `54c8db0afaaf0bacb952a9194c7ede2fb59accb6582f4481f34438c966429f79`
- Host SHA256: `ad83ca9855747e08d5ccccaa7640260f03f1bf7ce722c36e885dfe2508149725`

NIFM baseline: `build/apk-gpu-nifm1/d3host-recovery-debug.apk`:

- APK SHA256: `1077f0afd6d7304d2abad112c8a8cca517612be29f90753d0c85ab5576c08fc3`
- Host SHA256: `bfa0019738a621913291894bd6db602ccc949693227abb75afbb7e3ffa6bdc22`
- Guest SHA256 is unchanged from the historical build below.

### Historical mapping baseline

`build/apk-gpu-nvgpumap5/d3host-recovery-debug.apk`:

- APK SHA256: `b13e0d59fcce1d7ffa9adb3d4c9b2bfae0383da87fe75ba7d518d4602bcdbfad`
- Host SHA256: `1dc11a8b2824847ecc7f85d31f75259deb9ceca5bbd424d7a3d0f55b2db21ebb`
- Guest SHA256: `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`

Evidence under `gpu/probe/`:

- `frame-entry-rettrace4.txt`, `frame-exit-rettrace4.txt`: account stack damage.
- `logcat-localuser1.txt`: language initialization advances into real CPK reads.
- `logcat-nvshape1.txt`: first three guest ioctls after plain-reply repair.
- `logcat-nvgpumap3.txt`, `gpu-nvgpumap3.txt`: real shared GPU buffer mappings.
- `logcat-nvgpumap4.txt`: partial-overlap alias MapPhysicalMemory rejection;
  subsequently fixed to preserve existing mappings and commit uncovered gaps.
- `logcat-nvgpumap5.txt`: alive at 30-second capture, loading real CPKs.
  Android exit-info later records SIGSEGV at 08:01:11, PID 5967. The dump file is
  stale from the preceding run, so it must not be attributed to this SIGSEGV.
  A ptrace follow-up is in progress to identify the first fault.

## Regression evidence

Fourteen targeted Android-native suites pass on SM-X700, serial R52T90127WT:

`test_startup_services`, `test_nvdrv`, `test_guest_tls`,
`test_address_arbiter`, `test_sync`, `test_hipc_message`, `test_set_service`,
`test_save_filesystem`, `test_hid_memory`, `test_hid_service`, `test_applet_focus`,
`test_signal_chain`, `test_directory`, `test_nvdrv_gpu`.

All fourteen were rebuilt and passed at nvkind1 (`build/native-nvkind1-build.txt`
and `build/native-nvkind1-results.txt`). The later NFP change additionally passes
test_startup_services. `test_nvdrv_gpu` uses a mock C++ bridge to verify C-layer
mapping failure rollback, pin counts and kind-only subrange remaps; actual Eden
page-table behavior is evidenced separately by device GPU logs.

`test_guest_tls` executes the original guest SDK across four native threads,
1000 round trips each, and invokes the original game existence code for existing
and missing files. `test_startup_services` exercises actual HIPC serialization
for launch storage, account UID and plain nvdrv Ioctl3 input/output descriptors.
`test_nvdrv` checks handle lifecycle, outputs and reservation overlap errors.
These suites do not prove a game frame or complete Horizon semantics.

## Remaining work

1. Diagnose Particle resource count/limit and eviction eligibility along the
   preserved caller chain, without bypassing assertions or inflating game limits.
2. Complete actual GPU channel, GPFIFO submission, synchronization and presentation
   required by the guest. Binder/native-window and other inherited placeholders
   are not accepted as working graphics.
3. Harden shared-memory lifecycle: physical backing reuse after partial unmaps,
   reservation/mapping pin lifetime, surface destruction/recreation and errors.
4. Remove remaining inherited assertion bypasses and success-only service hooks
   as their real interfaces are implemented; cold-boot acceptance requires them
   not to conceal failures.

Only `com.d3mobile.host.recovery` is installed with `adb install -r`. Every probe
uses `run_probe.ps1 -Keep`. Do not clear/uninstall application data or use
`rebuild_and_probe.ps1`, which omits `-Keep`. No branch, commit or push was made.
