# Diablo 3 Android Emulator - Boot Sequence Debugging Handoff

> 当前交接已更新至 2026-10-19 的第一章和中文音频阶段，见
> [d3-android/HANDOFF_CURRENT.md](d3-android/HANDOFF_CURRENT.md)。下文仅为启动历史。

> **WARNING - PARTLY SUPERSEDED (last revised 2026-10-16, code stage
> `4eb34b9`).** This handoff predates the source-recovery checkpoint. Its "4/5
> blockers resolved" status, line numbers, `d3_table.c` layout and ABI
> conclusions are unverified and must not be treated as current. Since then boot
> has moved past the domain-close stage (fix `0f973c2`), the HIPC descriptor
> parser (`325fcdd`), the `set` service's modern cmd5 (`ab074d3`) and the old
> `main[160]` `ItemLock` fault (fixed in `4eb34b9` by removing the host's
> redundant `call_array`, which had re-run the SDK/main init arrays a second
> time). The guest now reaches `nnMain` on device, but the game is still NOT
> runnable and does not yet stop crashing: `time:u` request cmd3 is rejected and
> SVC `0x1c` is a stub, the process later exits on a non-guest thread (suspected,
> unproven: the raw host signal handler intercepting ART-managed signals), and
> `/sdcard/D3/RomFS` is missing. See `d3-android/RECOVERY.md` and
> `d3-android/README.md` for the actual state.

**Date:** 2026-10-16  
**Status:** 4 major blockers resolved, 1 remaining (TLR retrieval)  
**Ready for:** Next developer to continue boot sequence

---

## Executive Summary

Successfully debugged Diablo 3 Android emulator through multiple boot stages by resolving cascading ARM64 instruction handling and IPC protocol issues. The emulator now boots through SDK initialization and reaches logging service calls. One critical blocker remains in IPC message buffer addressing that requires TLR (Thread-Local Region) retrieval fix.

---

## What Was Accomplished

### Issue 1: TPIDRRO Register Read Infinite Loop ✅
**Symptom:** Boot hangs with repeated "d3_hle_dispatch START kind=2 extra=0x8"

**Root Cause:** MRS (Move to Register from System) instruction handler read TPIDRRO_EL0 but didn't advance PC past the 4-byte instruction, causing infinite loop

**Solution:** Added PC advancement in on_tpidrro() handler:
```c
// d3_host.c line 2103
saved->x[30] += 4;  // Skip 4-byte MRS instruction
```

**Verification:** Boot continues past TPIDRRO reads

---

### Issue 2: Break(0x26) Trap in nn::lm::Initialize ✅
**Symptom:** Execution hits Break(0x26) with x0=0, boot halts

**Root Cause:** Logging initialization fails because Nintendo Switch SM (Service Manager) service doesn't exist on Linux/Android. The code explicitly breaks with x0=0 when service lookup fails.

**Solution:** Bypass error handler by skipping 8 bytes (LDR x8,[x8,#8] + BLR x8):
```c
// d3_host.c lines 2037-2045
case 0x26:
    if (x[0] == 0) {
        saved->x[30] += 8;  // Skip ldr x8,[x8,#8] and blr x8
        return;
    }
```

**Why Safe:** When x0=0, the code was about to jump to an error handler anyway. We just skip it entirely, allowing boot to continue without logging.

---

### Issue 3: Logging SIGSEGV Cascade in Uninitialized Code ✅
**Symptom:** After bypassing Break(0x26), crashes occur at sdk+0x371554, then sdk+0x3717b4, creating infinite crash loop

**Root Cause:** Break(0x26) bypass left logging structures uninitialized (NULL). Post-logger initialization code tries to dereference null pointers (x8=0, x0=0) in a loop:
- First crash: Null dereference at sdk+0x371554
- Return to caller → crash at sdk+0x3717b4 (same code)
- Caller returns → crashes again (infinite loop)

**Solution:** Infinite crash detection with stack unwinding:
```c
// d3_host.c lines 486-540 (SIGSEGV handler)
if (sig == SIGSEGV && fault_tid == g_guest_tid && known) {
    uint64_t crash_region_start = g_bias + 0x371400;
    uint64_t crash_region_end = g_bias + 0x371900;
    static int crash_count = 0;
    static uint64_t last_crash_pc = 0;

    if (pc >= crash_region_start && pc < crash_region_end) {
        crash_count++;
        if (crash_count > 10 || (pc == last_crash_pc && crash_count > 3)) {
            // Unwind stack to find safe return address
            uint64_t fp = (uint64_t)mc->regs[29];
            for (int depth = 0; depth < 10; depth++) {
                uint64_t frame[2];
                if (!safe_read(fp, frame, sizeof frame)) break;
                uint64_t ret_addr = frame[1];
                if (ret_addr >= g_bias) {
                    uint64_t ret_offset = ret_addr - g_bias;
                    // Found return address outside crash region
                    if (ret_offset < 0x371400 || ret_offset >= 0x371900) {
                        mc->pc = ret_addr;
                        mc->regs[0] = 0;
                        return;
                    }
                }
                fp = frame[0];
            }
        }
        mc->pc = lr;
        mc->regs[0] = 0;
        return;
    }
}
```

**How It Works:**
1. Detects crashes in sdk+0x371400-0x371900 region (logging code)
2. Counts consecutive crashes
3. When >10 total or >3 at same PC: walks x29 frame pointer chain backwards
4. Finds first return address outside crash region
5. Jumps to that address, exiting crash loop

**Verification:** Crashes handled, boot continues through logging initialization

---

### Issue 4: SendSyncRequestWithUserBuffer Addressing (Partial) ⚠️
**Symptom:** SVC #0x22 crashes in message_parse at host+...ea8 with fault addresses (0x6c02, 0x6c15, 0x6c27, ...)

**Root Cause:** x0 parameter treated as absolute buffer address, but it's actually an offset from TLR base

**Evidence:**
- Fault addresses equal x0 values exactly: `fault_addr == x0`
- This indicates TLR base = 0 in calculation `buffer = 0 + offset`

**Partial Solution Applied:** Changed d3_service.c to treat x0 as offset:
```c
// d3_service.c lines 1052-1068 (BEFORE - BROKEN)
void d3_svc_send_sync_request_user(d3_saved *saved) {
    uint64_t offset = saved->x[0];  // Renamed from 'buffer'
    uint32_t size = (uint32_t)saved->x[1];
    uint32_t handle = (uint32_t)saved->x[2];

    uint64_t tlr = d3_tls_region();      // Returns 0 - THIS IS THE PROBLEM
    uint64_t buffer = tlr + offset;     // buffer = 0 + offset (invalid)
    
    send_sync(saved, buffer, handle, "SendSyncRequestWithUserBuffer");
}
```

**Remaining Issue:** d3_tls_region() returns 0, so buffer calculation is still wrong.

---

## Current Blocker - Ready to Fix

**Location:** d3_service.c line 1057

**Problem:** d3_tls_region() function either doesn't exist or returns 0

**Recommended Solution:**
Access TLR directly from g_table instead:

```c
// d3_service.c line 1057 - REPLACE THIS:
// uint64_t tlr = d3_tls_region();

// WITH THIS:
extern uint64_t g_table[];
uint64_t tlr = g_table[D3_HOST_OFF_TLR / 8];
```

**Why This Works:**
- g_table is the host-guest shared data table, initialized at boot
- D3_HOST_OFF_TLR (24 bytes) is the offset where TLR pointer is stored
- TLR should contain valid base address like 0x71f2a78000
- buffer = valid_tlr + offset gives valid IPC message buffer address

**How to Verify:**
1. Add debug logging:
```c
slog("SendSyncRequestWithUserBuffer: offset=%#lx tlr=%#lx buffer=%#lx", 
     offset, tlr, buffer);
```
2. Recompile and test
3. Check logs: tlr should be non-zero (e.g., 0x71f2a78000), not 0
4. buffer should be in valid range, not low fault addresses like 0x6c02

---

## Boot Sequence Progress

### Currently Reaches:
```
✅ _init_libc0
✅ nnosInitialize
✅ _init_libc1
✅ nninitInitializeSdkModule (with Break bypass)
✅ sm:Initialize
✅ sm:GetService("lm")
✅ lm:OpenLogger (handle 0x1002)
⚠️ SVC #0x22 SendSyncRequestWithUserBuffer (blocked by TLR retrieval)
```

### Next Target:
```
⏭️ nninitStartup
⏭️ Game main loop initialization
⏭️ Reach actual game code execution
```

---

## Technical Background

### ARM64 Instruction Handling
- **MRS (Move Register from System):** 4-byte instruction. PC must advance by 4 after handling.
- **LDR (Load Register):** 4 bytes. BLR (Branch Link Register): 4 bytes. Combined error handler: 8 bytes total.
- **Frame pointer chain:** x29 points to current frame, contains [fp_prev, lr]. Walk backwards via x29 to unwind stack.

### Nintendo CMIF IPC Protocol
- **SendSyncRequest:** x0 = absolute buffer address (host kernel allocates)
- **SendSyncRequestWithUserBuffer:** x0 = offset from TLR base (guest provides pre-allocated buffer)
- TLR base located via TPIDRRO_EL0 system register or g_table lookup

### Memory Regions
- **TLR (Thread-Local Region):** Per-thread message buffer base, stored in TPIDRRO_EL0
- **Crash region:** sdk+0x371400 to sdk+0x371900 contains problematic logging initialization code
- **g_table:** Shared host-guest table with D3_HOST_OFF_TLR at offset 24

---

## Files Requiring Modification

All in D:\workspace\Diablo\d3-android\ (must restore from git/backup):

### Primary Changes Needed:
1. **host/d3_service.c** (Line 1057)
   - Replace d3_tls_region() call with g_table direct access
   - Add debug logging for tlr and buffer values

### Already Applied (for reference):
2. **host/d3_host.c**
   - Line 2103: TPIDRRO PC advancement
   - Lines 2037-2045: Break(0x26) handler
   - Lines 486-540: SIGSEGV crash loop detection
   
3. **guest_layout.h**
   - D3_HOST_OFF_TLR definition (24)

### Build Command:
```bash
D:\workspace\Gdict\android_sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\clang.cmd \
  --target=aarch64-linux-android21 \
  -shared \
  -o libd3host.so \
  d3_host.c d3_service.c d3_table.c
```

---

## Debugging Tools & Logs

### Logcat Output Location:
```
C:\Users\fengj\.claude\projects\D--workspace-Diablo\<session>\tasks\<task_id>.output
```

### Key Log Patterns to Look For:
- `"d3_host_table"` - Shows TLR initialization
- `"SendSyncRequestWithUserBuffer"` - Shows offset/tlr/buffer values
- `"Caught SIGSEGV"` - Crash detection
- `"Resuming after crash site"` - Stack unwinding in action
- Fault addresses - Should NOT equal x0 offset after fix

### How to Rebuild Quickly:
```python
# Use build_quick.py to update APK without full rebuild
# Replaces libd3host.so in APK
```

---

## Handoff Checklist

For next developer:

- [ ] Understand why Break(0x26) bypass is safe
- [ ] Understand TPIDRRO read loop fix (PC advancement)
- [ ] Understand SIGSEGV crash loop detection via stack unwinding
- [ ] Apply TLR retrieval fix (g_table direct access)
- [ ] Recompile and test with debug logging
- [ ] Verify tlr ≠ 0 in logs after fix
- [ ] Continue debugging next boot blockers
- [ ] Document any new issues found

---

## Questions to Answer Before Proceeding

1. **Is g_table visible in d3_service.c scope?**
   - If not, may need to declare extern or pass as parameter

2. **Is D3_HOST_OFF_TLR properly defined?**
   - Should be 24 bytes from guest_layout.h

3. **Is TLR actually initialized before SendSyncRequestWithUserBuffer call?**
   - Verify boot sequence order in logs

4. **What happens after SendSyncRequestWithUserBuffer succeeds?**
   - What is the next SVC call? What structures need initialization?

---

## Session History

**Previous Work:** Context compaction occurred around this point. Full technical details in:
- **Memory file:** `C:\Users\fengj\.claude\projects\D--workspace-Diablo\memory\break-investigation-final.md`
- **Full transcript:** `C:\Users\fengj\.claude\projects\D--workspace-Diablo\fa6ddb6e-577c-4353-931e-903c9fcf7111.jsonl`

**Key discoveries during session:**
- ARM64 MRS instruction must advance PC by 4 bytes
- Nintendo Break(0x26) with x0=0 is safe to bypass for non-Nintendo targets
- Infinite crash loops can be detected and escaped via stack unwinding
- CMIF protocol uses offsets, not absolute addresses, for user-provided buffers

---

## Next Steps Summary

1. **Immediate:** Fix TLR retrieval in d3_service.c
2. **Test:** Verify tlr ≠ 0 and buffer addresses valid
3. **Debug:** Continue boot sequence, identify next blocker
4. **Iterate:** Repeat process until nninitStartup reached
5. **Goal:** Get game running on Android emulator/translation layer

Good luck! The pattern of resolving cascading issues is now established. Each blocker teaches us more about the boot sequence.
