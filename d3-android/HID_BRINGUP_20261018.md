# HID bring-up evidence — 2026-10-18

## Result

The guest now creates an `IAppletResource` session, obtains its shared-memory
handle, maps the 256 KiB block read-only, and receives seeded Npad state. The
controller applet's 12-byte result now reaches the guest through its C receive
buffer. These are verified on SM-X700 `R52T90127WT` using the recovery package.

**M2 remains open: no guest nvdrv ioctl was observed.** The controller applet
still loops even after its result is copied successfully. This run does not
establish working controller input, a real game frame, or playable gameplay.

## Fixes

1. `hid` command 0 returns an `IAppletResource` interface: a MOVE session in
   plain mode or a child object in domain mode. It does not return shared memory
   or an output applet-resource user id.
2. `IAppletResource` command 0 returns a COPY shared-memory handle. Plain and
   domain dispatch both support it; unknown commands and allocation failures
   return errors.
3. HIPC replies describe their own optional handle header and do not echo the
   request's PID header. The original HID reply produced a proxy using invalid
   session handle `0x6`; the corrected session is a real host-allocated handle.
4. `map_shared_at` temporarily enables host writes while seeding the HID block,
   then restores the guest-requested protection. Previously the first successful
   read-only map crashed inside `d3_hid_seed` with `SEGV_ACCERR` at map + `0x9a00`.
5. Storage buffer decoding walks X and A/B/W descriptors and then C receive
   descriptors at the end of the declared raw-data area. It no longer treats
   CMIF argument words as a guessed trailing mapped descriptor.

The captured controller-result request has `w0=0x01000006`, `w1=0x0c0f`, an empty
B descriptor at words 2–4, and its actual C descriptor at words 20–21. The
descriptor encodes a 48-bit address and a 16-bit size. The previous decoder
reported no buffer and returned success without copying the result.

## Final APK and probe

- APK: `build/apk-gpu-hid-cbuf1/d3host-recovery-debug.apk`
- APK SHA-256: `c7efe7ca45b36b1e747b58491c39d6700ec0c3e6920d47c25fe65d416a10e37e`
- Host SHA-256: `80cbe1f2d4bdeb64a81388722c4a36feac6a89ef279f4fcde54c7e2cb147a897`
- Guest SHA-256: `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`
- Probe: `gpu/probe/logcat-hid-cbuf1.txt`, requested 18-second observation.
- Package: `com.d3mobile.host.recovery`; installed using `adb install -r`.
- Existing app data was preserved; every probe used `run_probe.ps1 -Keep`.

The final probe contains:

| Marker | Count |
| --- | ---: |
| `hid::CreateAppletResource ... -> session` | 1 |
| `hid::IAppletResource::GetSharedMemoryHandle` | 1 |
| `MapSharedMemory ... size=0x40000 perm=1` | 1 |
| `hid: seeded npad 0` | 1 |
| Controller applet starts (`applet=0xc`) | 2625 |
| Successful 12-byte storage reads | 2623 |
| `AbortImpl caller=` | 0 |
| `nvdrv::Ioctl#` | 0 |

The process was alive at capture and was force-stopped afterwards to end the
busy loop. No Npad style/state API calls were observed by temporary one-shot
probes during `hid-state1`; those probes were removed from the final build.
That observation is bounded to that run and those two entry points.

## Validation

The final sources compile with the NDK's `-Wall -Wextra -Werror`. These five
Android-native suites pass on the tablet:

- `test_hid_service`: plain/domain interface factory, COPY shared memory,
  request-PID/reply shape, session close, allocation errors, and an actual
  controller result read using the captured B+C descriptor layout. Sentinel
  bytes verify that exactly 12 bytes are written; truncated C arrays are refused.
- `test_hid_memory`: read-only and read-write shared mappings. It verifies the
  seeded bytes and that writing through the kernel to the read-only map fails.
- `test_hipc_message`
- `test_set_service`
- `test_applet_focus`

`build/hid-final-validation.txt` contains the final test output. The isolated
service tests now link `tests/service_host_stubs.c` for host tracing/event
callbacks; production builds still use the real callbacks.

The broader regression set is not all green. `test_time_service` fails at line
290 because it requires a MOVE handle for domain `GetSharedMemory`, while the
existing `reply_domain_handle` uses COPY. The same COPY implementation exists
in HEAD; this session does not modify time-service semantics. The existing
`test_stack_memory` also fails to compile because its `on_tpidrro` call still
uses the old two-argument signature. Those unrelated expectations remain open.

## Other observations and next investigation

- `hid-session2` progressed through account commands 140 and 150 to
  `fsp-srv cmd=51`, then exited with SIGSEGV according to Android exit-info.
  Its `d3-crash` file was stale from `hid-session1`; do not attribute that dump
  to session 2. The old crash file was preserved on-device under
  `files/d3-crash-before-hid-session3.txt` before subsequent probes.
- A diagnostic run with the existing ptrace tracer (`hid-session3`) stalled
  with a mutex-owner mismatch and reported `sdk+0x21fbc0` as its last dispatch.
  Its trace includes a `SharedPreferenc` thread's ART fault. This does not prove
  the cause of session 2's SIGSEGV. The trace flag was removed afterwards.
- `run_probe.ps1` formerly counted hook-registration messages as aborts. Its
  abort counter now matches only `AbortImpl caller=`. Old printed totals of 3
  can mean zero actual calls.

Next, identify who retries `nn::hid::ShowControllerSupport`, and capture the
return from `ShowControllerSupportCore` (merged `0x271dc0`) plus the caller's
decision. The result bytes are now delivered, so a missing copy is no longer
a sufficient explanation for the loop. Investigate the intermittent TLS/mutex
issue separately. Then continue resource/save-filesystem initialization and
nvdrv bring-up. Do not claim M2 until an actual guest ioctl is recorded.

## Remaining scope

The outstanding path to M2 still includes the controller/app initialization
loop, intermittent synchronization failures, and any filesystem or graphics
initialization blockers exposed next. Full nvdrv semantics, GPU submission,
real presentation, resource staging, input, audio, saves, and repeatable cold
starts remain beyond that. Earlier time estimates are rough planning budgets,
not measured completion forecasts.
