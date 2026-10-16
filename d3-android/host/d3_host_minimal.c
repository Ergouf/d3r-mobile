// d3_host_minimal.c - Minimal working implementation
// This is a functional stub that can compile and load
// Full implementation coming from child agent

#include <jni.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <sys/ucontext.h>
#include <unistd.h>
#include "guest_layout.h"
#include "d3_service.h"

#ifndef SYS_gettid
#define SYS_gettid __NR_gettid
#endif

// Global variables
uint64_t g_table[1024];
uint64_t g_bias = 0;
uint64_t g_guest_tid = 0;
int g_loud = 5;

// Forward declarations
extern void d3_svc_send_sync_request_with_user(d3_saved *saved);

// Safe memory read
int safe_read(uint64_t addr, void *buf, size_t size) {
    // Minimal implementation - just read directly
    // In real implementation, would use process_vm_readv
    memcpy(buf, (void*)addr, size);
    return 1;
}

// Set register value
void set_saved(d3_saved *saved, uint32_t reg, uint64_t value) {
    if (reg < 31) {
        saved->x[reg] = value;
    } else if (reg == 31) {
        saved->pc = value;
    }
}

// Handle TPIDRRO_EL0 read
void on_tpidrro(d3_saved *saved, uint64_t reg_num) {
    uint64_t tlr = g_table[D3_HOST_OFF_TLR / 8];
    if (reg_num > 30) {
        printf("[ERROR] tpidrro register out of range: %lu\n", (unsigned long)reg_num);
        return;
    }
    if (!tlr) {
        printf("[WARNING] tpidrro before TLR set\n");
    }
    printf("[TPIDRRO] reg x%lu = 0x%lx\n", reg_num, tlr);
    set_saved(saved, (uint32_t)reg_num, tlr);
    saved->x[30] += 4;  // Advance PC past 4-byte MRS instruction
}

// Handle Break(0x26)
void handle_break_0x26(d3_saved *saved) {
    uint64_t x0 = saved->x[0];
    printf("[BREAK] Break(0x26) with x0=%#lx\n", x0);

    if (x0 == 0) {
        // Safe to bypass - service not found
        printf("[BREAK] x0=0, skipping 8 bytes (LDR+BLR error handler)\n");
        saved->x[30] += 8;
        return;
    }
    // Other break codes would need different handling
}

// SIGSEGV handler (minimal version)
void handle_sigsegv(int sig, siginfo_t *info, void *ctx) {
    ucontext_t *ucontext = (ucontext_t *)ctx;
    mcontext_t *mc = &ucontext->uc_mcontext;

    uint64_t pc = mc->pc;
    uint64_t fault_addr = (uint64_t)info->si_addr;

    printf("[SIGSEGV] pc=%#lx fault=%#lx\n", pc, fault_addr);

    // Check if in crash region
    uint64_t crash_region_start = g_bias + D3_CRASH_REGION_START;
    uint64_t crash_region_end = g_bias + D3_CRASH_REGION_END;

    if (pc >= crash_region_start && pc < crash_region_end) {
        printf("[SIGSEGV] In crash region, attempting escape\n");
        // Simple escape - just advance PC or return to LR
        mc->pc = mc->regs[30];
        mc->regs[0] = 0;
    }
}

// SIGTRAP handler (Break instruction)
void handle_sigtrap(int sig, siginfo_t *info, void *ctx) {
    printf("[SIGTRAP] Break instruction caught\n");
    // Decode and handle specific break code
}

// HLE dispatcher
int d3_hle_dispatch(d3_saved *saved, int kind, uint64_t extra) {
    switch (kind) {
        case 0x8:  // TPIDRRO_EL0 read
            printf("[HLE] TPIDRRO read (reg x%lu)\n", extra);
            on_tpidrro(saved, extra);
            return 1;
        case 0x26:  // Break(0x26)
            printf("[HLE] Break(0x26)\n");
            handle_break_0x26(saved);
            return 1;
        case 0x22:  // SVC #0x22 SendSyncRequestWithUserBuffer
            printf("[HLE] SVC #0x22\n");
            d3_svc_send_sync_request_with_user(saved);
            return 1;
        default:
            printf("[HLE] Unhandled: kind=%d extra=%lu\n", kind, extra);
            return 0;
    }
}

// JNI entry point
jint JNI_OnLoad(JavaVM *vm, void *reserved) {
    printf("[JNI] OnLoad called\n");

    // Register signal handlers
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = handle_sigsegv;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigaction(SIGSEGV, &sa, NULL);

    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = handle_sigtrap;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigaction(SIGTRAP, &sa, NULL);

    printf("[JNI] Signal handlers registered\n");

    return JNI_VERSION_1_6;
}

void JNI_OnUnload(JavaVM *vm, void *reserved) {
    printf("[JNI] OnUnload called\n");
}
