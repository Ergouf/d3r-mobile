# d3-android - Diablo 3 Android Emulation Layer

This directory contains the custom ARM64 emulation and IPC translation layer for running Diablo 3 on Android through a translation layer.

## Directory Structure

```
d3-android/
├── host/
│   ├── d3_host.c          - ARM64 instruction handling, signal handlers
│   ├── d3_service.c       - IPC service call handlers (SVC #0x22, etc)
│   ├── d3_table.c         - Shared host-guest data table
│   ├── guest_layout.h     - Memory layout and struct definitions
│   ├── d3_service.h       - Service handler declarations
│   └── Makefile           - Build configuration
└── README.md
```

## Recent Fixes Applied

### Issue 1: TPIDRRO Infinite Loop ✅
- **File:** d3_host.c line 2103
- **Fix:** Added PC advancement in on_tpidrro() - skip 4-byte MRS instruction

### Issue 2: Break(0x26) Crash ✅
- **File:** d3_host.c lines 2037-2045
- **Fix:** Skip 8-byte error handler when x0=0

### Issue 3: Logging SIGSEGV Loop ✅
- **File:** d3_host.c lines 486-540
- **Fix:** Infinite crash detection with stack unwinding

### Issue 4: TLR Retrieval (CURRENT) ⚠️
- **File:** d3_service.c line 1057
- **Status:** READY TO FIX
- **Fix:** Replace d3_tls_region() with `g_table[D3_HOST_OFF_TLR / 8]`

## Build Instructions

### Windows (with Android NDK installed)

```bash
cd d3-android
make
```

This will:
1. Compile d3_host.c, d3_service.c, d3_table.c
2. Link as shared library (libd3host.so)
3. Output to `out/libd3host.so`

### Clean build

```bash
make clean
make
```

## Next Steps

1. **Verify TLR Retrieval Fix:**
   - Check that g_table[D3_HOST_OFF_TLR/8] is properly initialized
   - Verify tlr ≠ 0 in debug logs
   - Ensure buffer addresses are valid (not low fault addresses like 0x6c02)

2. **Test Boot Sequence:**
   - Run emulator with instrumented libd3host.so
   - Monitor logs for SendSyncRequestWithUserBuffer messages
   - Verify boot progresses past SVC #0x22

3. **Continue Debugging:**
   - Identify next blocker in boot sequence
   - Document findings in HANDOFF.md

## Debugging

Enable debug logging by checking logs:
```bash
# Look for d3_service debug output
logcat | grep "d3_service"

# Check for crash detection
logcat | grep "Caught SIGSEGV"
```

Key debug patterns in code:
- `slog()` - Custom logging macro in d3_service.c
- Check TLR value: Should be non-zero (e.g., 0x71f2a78000)
- Check buffer address: Should be in valid range, not low addresses

## References

- **ARM64 ABI:** System registers, MRS instruction format, frame pointers
- **Nintendo CMIF:** IPC protocol, user buffer handling
- **Previous Session:** See HANDOFF.md for full technical context
