// d3_host.c - ARM64 instruction handling and IPC dispatch
// This is a reconstruction based on HANDOFF.md specifications

#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/ucontext.h>
#include "guest_layout.h"
#include "d3_service.h"

// Global state
extern uint64_t g_bias;
extern uint64_t g_guest_tid;
extern uint64_t g_table[];

// SIGSEGV handler with crash detection and stack unwinding
void handle_sigsegv(int sig, siginfo_t *info, void *ctx) {
    ucontext_t *ucontext = (ucontext_t *)ctx;
    mcontext_t *mc = &ucontext->uc_mcontext;

    uint64_t pc = mc->pc;
    uint64_t lr = mc->regs[30];
    uint64_t fault_addr = (uint64_t)info->si_addr;
    pid_t fault_tid = syscall(SYS_gettid);

    int known = (pc >= g_bias && pc < g_bias + 0x10000000);

    // Infinite crash loop detection and stack unwinding
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
}

// Handle TPIDRRO_EL0 system register read
// Issue: MRS instruction didn't advance PC, causing infinite loop
// Fix: Advance PC by 4 bytes (MRS is 4-byte instruction)
void on_tpidrro(d3_saved *saved) {
    // TPIDRRO_EL0 handler
    // saved->x[0] contains the value that would be read

    // CRITICAL FIX: Advance PC past the MRS instruction
    saved->x[30] += 4;  // Skip 4-byte MRS instruction
}

// Handle Break(0x26) trap in nn::lm::Initialize
// Issue: Service not found, code tries to jump to error handler at x8=[x8+8]
// Fix: For x0==0 case (error condition), skip 8 bytes to bypass error handler
void handle_break_0x26(d3_saved *saved) {
    uint64_t x0 = saved->x[0];

    // This is Break(0x26) with x0=0 - safe to bypass
    if (x0 == 0) {
        // Skip LDR x8,[x8,#8] (4 bytes) + BLR x8 (4 bytes) = 8 bytes total
        saved->x[30] += 8;  // Skip error handler
        return;
    }

    // Other break codes should crash normally
    return;
}

// HLE dispatcher for system calls
int d3_hle_dispatch(d3_saved *saved, int kind, int extra) {
    switch (kind) {
        case 0x8:  // TPIDRRO_EL0 read
            on_tpidrro(saved);
            return 1;  // Continue execution

        case 0x26:  // Break instruction
            if (extra == 0x26) {
                handle_break_0x26(saved);
                return 1;
            }
            break;
    }

    return 0;  // Not handled
}

// Safe memory read helper
int safe_read(uint64_t addr, void *buf, size_t size) {
    // Implementation depends on platform
    // This should safely read guest memory
    return 1;  // Placeholder
}
