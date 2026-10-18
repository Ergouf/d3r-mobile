# D3 on Android — current handoff (read this first)

Goal: run the **Diablo III Eternal Collection** Switch guest (XCI update version) on
the Galaxy Tab S8 (SM-X700) through a host that loads the guest ELF **in-process**
and emulates Horizon OS services (HLE). Milestones:

- M0/M1 — **done**: Eden's Vulkan clear + composite reach the screen
  (`d3-android/gpu/probe/m1-clear-*.png`, `m3-composite-*.png`).
- **M2 — open**: the guest must actually issue nvdrv ioctls (`nvdrv::Ioctl` > 0 in the
  probe log). Currently **0**.
- M3 — open: first real game frame.

Long history (rounds 1–36 of the previous session plus the last four rounds) is in
`d3-android/HANDOFF_GPU_M2.md`. This file is the short, current, self-contained view.

---

## 1. Where the boot stands right now

Run `cv1` (latest probe) shows:

- the guest image is mapped, **784 recovered relocations** applied;
- the real SDK start-up runs and **returns**: `call nninitStartup` / `back nninitStartup`;
- the library applet framework completes a full cycle (creator → 3 storages →
  `Start` → state wait → `PopOutData`);
- parental-control (`pctl`) factory sequence completes;
- then it dies in a guest assert:

```
patch null condition variable wait at ... OK
AbortImpl caller = sdk+0x4b4bc        ("this == NULL!")
abort operand [sp+8] = 0x1a80a        (module 10, description 212)
```

`0x4b4bc` is inside `nn::account::IsNetworkServiceAccountAvailable`; that code only
accepts `(result & 0x3FFFFF) == 0x2C7C` (Account/22, "not initialised") and aborts on
anything else. So *some* call on this path returned module-10/212 instead of Account/22.

Logs to read first: `d3-android/gpu/probe/logcat-cv1.txt`,
`d3-android/gpu/probe/d3-crash-cv1.txt`.

---

## 2. Device / environment

| item | value |
|---|---|
| device | SM-X700, serial `R52T90127WT` |
| package | `com.d3mobile.host.recovery` (debuggable, `run-as` works) |
| start | `adb shell am start -n com.d3mobile.host.recovery/com.d3mobile.host.MainActivity --ez autostart true` |
| data root | `/data/user/0/com.d3mobile.host.recovery/files/runtime` (logs, flags) |
| python | `C:\Users\fengj\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe` |
| NDK | `D:\workspace\Gdict\android_sdk\ndk\28.2.13676358` |
| adb | `D:\workspace\Gdict\android_sdk\platform-tools\adb.exe` |
| disk | XCI (21.9 GB) present at repo root; `reference/extract/ncas` was deleted (regenerable from the XCI with `nstool`/`hactool` + `prod.keys`); `romfs`/`romfs_update` still present |

---

## 3. Build / probe commands

Full iteration (build host → package APK → install → probe):

```powershell
pwsh -File d3-android/tools/rebuild_and_probe.ps1 -Tag <tag> -Seconds 28
```

Manual pieces (when the script is inconvenient):

```powershell
py -I d3-android/tools/build_host.py --with-gpu `
   --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime `
   --private-root /data/user/0/com.d3mobile.host.recovery `
   --output-dir d3-android/build/host-gpu
py -I d3-android/tools/build_apk.py --host d3-android/build/host-gpu/libd3host.so `
   --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so `
   --output-dir d3-android/build/apk-gpu-<tag> `
   --keystore d3-android/build/apk-gpu-waitn/local-debug.keystore
adb install -r d3-android/build/apk-gpu-<tag>/d3host-recovery-debug.apk
pwsh -File d3-android/tools/run_probe.ps1 -Name <tag> -Seconds 28
```

Eden's GPU archive (only needed when Eden sources change, or if
`build/libeden_gpu.a` is missing): `pwsh -File d3-android/gpu/build_gpu.ps1`.

**Gotchas**

- `-SkipBuild` requires `build/apk-gpu-<tag>` to already exist; otherwise it probes
  whatever is installed, silently.
- `build/apk-gpu-waitn/local-debug.keystore` must exist (the shared signing key). If
  it is lost, run `build_apk.py` **without** `--keystore` once and copy the generated
  keystore there. A new keystore means a new signature → `adb uninstall` first.
- Never delete `d3-android/gpu/probe/*.cpp`, `coverage*.json`, `m1-*.png`,
  `m3-*.png` — they are tracked project assets (restore with `git checkout --
  d3-android/gpu/probe/`).

---

## 4. Architecture in one page

**Guest image** — `recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so`
(33 MB file, 54 MB image). It is a *repacked merge* of the update build's `main` and
`sdk` modules, mapped 1:1 at a random base (`g_bias`) in the host process. Offsets in
logs (`sdk+0x…`, `main+0x…`, `veneer+0x…`) are image offsets.

Merged layout (`d3-android/guest_layout.h`): sdk at `0x00010000`, **main at
`0x01000000`**, veneer at `0x03000000`, host table at `0x03100000`.

**Loader** (`load_guest()` in `d3-android/host/d3_host.c`): maps the PT_LOAD segments,
applies `R_AARCH64_RELATIVE` from `.dynamic`, then applies the **784 recovered
relocations** from `host/guest_relocs.h`, then installs 66 hook sites and a few code
patches, then sets segment protections.

**Recovered relocations** — the repack kept only `RELATIVE`, dropping 246 `ABS64`
(vtables → `__cxa_pure_virtual`), 9 `GLOB_DAT` (`__rel_dyn_*`/`__rel_plt_*`) and 529
`JUMP_SLOT` (main's imports from sdk/libc). `tools/gen_guest_relocs.py` regenerates
the table from `reference/extract/exefs_update/main.nso0`; it writes
`host/guest_relocs.h` (784 rows, 0 unresolved). **Do not hand-edit that header.**

**Symbol file** — `reference/d3-symbols/sdk.symbols.json` (25142 entries) holds
**sdk-module-relative** offsets: merged offset = value + `0x10000`. Verified with
`nninitInitializeSdkModule` (file 0x29d960 vs host `D3_SYM_` 0x2ad960) and by
disassembling `__cxa_pure_virtual` at merged `0x004d7bd8`.

**Veneer** — the guest image contains NintendoSDK's own syscall veneer at
`0x03000000`: each 32-byte stub carries `{kind, extra, arg}` and branches to the
dispatcher, which switches TPIDR_EL0 to the host TP (`[table+8]`), calls
`[table]` (host dispatcher) and switches back. `nn::os` mutexes/events and the SDK's
memory functions go through it. Our host writes the table at `0x03100000`.

**Hooks** — `hook_stub.S` patches 16-byte guest sites with
`ldr x16,[pc,#8]; br x16; <literal>`; the stub saves x0–x8/x29/x30, switches to the
calling thread's host TP (`d3_host_tp_current()`), records
`g_hook_tls{guest_lr, host_tp, guest_tp}`, calls `g_hook_bodies[index]`, restores the
guest TP and returns. Hook bodies receive up to 6 args. **Every patch must stay inside
16 bytes and must never use a direct `b` into the host library.**

**Service layer** (`d3_service.c`) — CMIF/HIPC parsing plus HLE for `sm`, `fsp-srv`,
`lm`, `Logger`, `set`, `time`, `nvdrv`, `vi` (manager/app), `hid`, `aoc`, `nns`,
`pctl`, `appletOE` (application proxy, application functions, self/window/debug
controllers, library-applet framework, storage/accessor), `acc:u0`, `nifm:u`.
Unimplemented commands answer `0x278` (CMIF "unsupported") and are logged.

**Sync layer** (`d3_sync.c`) — emulates Horizon mutex/condition waits
(`svcArbitrateLock/Unlock`, `svcWaitSynchronization*`). Horizon signals "waiters
exist" with bit `0x40000000`, and the guest's **fast unlock path only takes the slow
path when that bit is set** — `d3_sync_lock` must set it before sleeping (it does now).

**Signals** — `crash_handler` dumps to `files/d3-crash.txt` and logs
`AbortImpl caller=…`, `abort operand [ptr] = value`, guest stack symbols. SIGSEGV/
SIGBUS/SIGABRT are **not** forced into our handler by default (that broke ART's
null-check recovery and killed the process); `files/d3-host-force-signals` re-enables
the forcing if ever needed.

**Stall watchdog** — the host logs `stall: no svc for N ms, … last dispatch kind=…
lr=…` when the guest stops making svc calls; this is how guest spin/deadlock sites
were found.

---

## 5. Things that were fixed the hard way (do not regress)

1. **Relocations** — see §4. Symptom if lost: `HID/1` at `sdk+0x25d614`, `0x20b` at
   `sdk+0x8ff2c`, wild jumps into `0x48xxxxxx`.
2. **Signal forcing** — forcing the kernel SIGSEGV slot to our handler bypassed
   libsigchain and turned ART's routine null checks into process death.
3. **Thread pointer** — guest threads must register `__builtin_thread_pointer()`, not
   `pthread_self()` (bionic's `pthread_t` is not the TLS base).
4. **Account asserts** — two code patches in `install_guest_hooks` neutralise the
   Nintendo Account authorisation asserts (`sdk+0x4c2f8`, `sdk+0x4c328`).
5. **`nn::hid::CreateAppletResource` is hid command 0**, not 100 (100 is
   `SetSupportedNpadStyleSet`). Getting this wrong makes the engine relaunch the
   Controller applet forever.
6. **Library applet semantics** — signal the applet-state event on `Start`, keep the
   "library applet launchable" event level-triggered, and return
   `ControllerSupportResultInfo` (0xC bytes: 1 player, player 1, success) from
   `PopOutData`.
7. **Storage buffers** — `IStorageAccessor` requests carry the buffer descriptor at
   `magic+6` (size, address, flags), not in the header; and a missing buffer means
   "nothing to copy", not an error.
8. **Mutex wait bit** — see §4 sync layer.
9. **CMIF reply shape** — result goes at `payload+2`, params from `payload+4`, and a
   domain object reply writes `1` at `frame` plus the object id at `payload+4`.

---

## 6. Immediate next steps (in order)

1. **Explain `sdk+0x4b4bc` (`0x1a80a`)** — decode module 10 / description 212, find which
   HLE call returned it (grep the log for the last service calls before the abort),
   and make that call answer Account/22 (`0x2C7C`) or success as appropriate. The
   relevant function is `nn::account::IsNetworkServiceAccountAvailable`
   (`sdk+0x4b450`); it only tolerates `(result & 0x3FFFFF) == 0x2C7C`.
2. **hid shared memory** — `MapSharedMemory` never happens, so `d3_hid_seed()` never
   runs and the engine sees no controller. Either make the SDK's
   `SharedMemoryAccessor::Activate` path work (it currently aborts with `HID/1`
   because the map helper's PLT slot was unresolved — check whether that is fixed now
   that the 784 relocations are applied) or map a synthetic block and seed it.
3. **romfs** — the engine will need the game's data. `reference/extract/romfs*` holds
   it (29 GB); the guest's `fsp-srv` will have to serve those files. The last observed
   file call was `fsp-srv cmd=51 -> fs not-found`.
4. **nvdrv** — once the boot reaches graphics init, `nvdrv::Open`/`Initialize` run and
   the first `nvdrv::Ioctl …` lines appear (the host already logs and acks them). That
   is M2. Then real ioctl semantics are needed for M3 — mine
   `reference/eden/src/core/hle/service/nvdrv/*` (37 files: `nvhost_gpu`,
   `nvhost_as_gpu`, `nvmap`, `syncpoint_manager`, `ioctl_serialization.h`).

---

## 7. Tool inventory (`d3-android/tools`)

| tool | purpose |
|---|---|
| `rebuild_and_probe.ps1` | build host → package APK → install → probe |
| `run_probe.ps1` | start app, wait, dump `logcat-<name>.txt`, crash dump, tombstone |
| `build_host.py`, `build_apk.py` | compile host; package + sign APK |
| `gen_guest_relocs.py` | regenerate `host/guest_relocs.h` from the original NSOs |
| `nso_reloc.py`, `nso_info.py` | inspect NSO dynamic/relocation tables (works on `*.nso0`) |
| `dis_guest.py` | disassemble guest image offsets (`py -3 dis_guest.py <so> <vaddr> <size>`) |
| `find_calls.py`, `find_writes.py` | find `bl`/`b` call sites and `adrp`+`str` writers |
| `sdk_sym.py` | look up a name in `sdk.symbols.json` (remember: **+0x10000**) |

External reference tree: `reference/eden` (full recent checkout — nvdrv, hid_core,
am, android frontend, video_core), `reference/extract/exefs*` (original NSOs),
`reference/d3-symbols`, `reference/tools/{nstool,hactool}` + `prod.keys`.

---

## 8. Ground rules from the previous sessions

- Validate every change on the real device with a probe; do not claim progress from
  code alone.
- Keep hook sites at exactly 16 bytes, keep generated tables generated, and keep the
  HLE answers shaped like the real ones (result code + param words) — the SDK aborts
  on unexpected shapes.
- When a run dies, first distinguish: tombstone (real signal) vs `d3-crash.txt` (our
  handler) vs silent death (ActivityManager "has died", no signal) vs stall
  (`stall:` watchdog line).
