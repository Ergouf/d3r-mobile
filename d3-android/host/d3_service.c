// d3_service.c - IPC service call handlers
// This is a reconstruction based on HANDOFF.md specifications

#include <stdint.h>
#include <stdio.h>
#include "guest_layout.h"

// Forward declarations
extern uint64_t g_table[];
extern void send_sync(void *saved, uint64_t buffer, uint32_t handle, const char *name);

// Debug logging macro
#define slog(fmt, ...) printf("[d3_service] " fmt "\n", ##__VA_ARGS__)

// Handle SVC #0x22 - SendSyncRequestWithUserBuffer
// Issue: TLR (Thread-Local Region) retrieval returned 0
// Fix: Access TLR directly from g_table instead of calling d3_tls_region()
void d3_svc_send_sync_request_user(void *saved_ptr) {
    // Cast saved context
    struct {
        uint64_t x[31];  // x0-x30
        uint64_t pc;
        uint64_t pstate;
    } *saved = (void *)saved_ptr;

    uint64_t offset = saved->x[0];   // Offset from TLR base (NOT absolute address!)
    uint32_t size = (uint32_t)saved->x[1];
    uint32_t handle = (uint32_t)saved->x[2];

    // CRITICAL FIX: Replace d3_tls_region() with direct g_table access
    // d3_tls_region() was returning 0, breaking buffer address calculation

    // TLR is stored at offset 24 (D3_HOST_OFF_TLR) in the shared table
    uint64_t tlr = g_table[D3_HOST_OFF_TLR / 8];

    // Now calculate the actual buffer address
    uint64_t buffer = tlr + offset;

    // Debug logging to verify the fix
    slog("SendSyncRequestWithUserBuffer: offset=%#lx tlr=%#lx buffer=%#lx handle=%#x",
         offset, tlr, buffer, handle);

    // If tlr is still 0, something is wrong
    if (tlr == 0) {
        slog("ERROR: TLR is 0! Buffer calculation will be wrong");
        slog("  offset=%#lx (x0)", offset);
        slog("  buffer will be=%#lx (same as offset)", buffer);
    }

    send_sync(saved_ptr, buffer, handle, "SendSyncRequestWithUserBuffer");
}

// Placeholder for other SVC handlers
void d3_svc_send_sync_request(void *saved) {
    slog("SendSyncRequest (SVC #0x21) - not yet implemented");
}

void d3_svc_get_thread_id(void *saved) {
    slog("GetThreadId (SVC #0xE0) - not yet implemented");
}
