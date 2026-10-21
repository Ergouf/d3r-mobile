// d3_service_minimal.c - Minimal IPC service implementation
// Full implementation coming from child agent

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "guest_layout.h"
#include "d3_service.h"

// Forward declarations
extern uint64_t g_table[];
extern int g_loud;

// Stub implementations of service handlers
int handle_sm_command(uint32_t cmd, uint32_t request_id, const void *input) {
    printf("[SM] Command %u\n", cmd);
    return 0;  // Success
}

int handle_lm_command(uint32_t cmd, uint32_t request_id, const void *input) {
    printf("[LM] Command %u\n", cmd);
    return 0;  // Success
}

int handle_logger_command(uint32_t cmd, uint32_t request_id, const void *input) {
    printf("[Logger] Command %u\n", cmd);
    return 0;  // Success
}

// Parse incoming CMIF message
int message_parse(cmif_header *msg, uint32_t size) {
    printf("[CMIF] Parsing message, size=%u\n", size);
    if (size < sizeof(cmif_header)) {
        printf("[CMIF] Message too small\n");
        return -1;
    }
    printf("[CMIF] Magic=%#x version=%u\n", msg->magic, msg->version);
    return 0;
}

// Build response message
void message_build_response(cmif_header *msg, int result) {
    printf("[CMIF] Building response, result=%d\n", result);
    memset(msg, 0, sizeof(*msg));
    msg->magic = 0x4349464D;  // 'CMIF'
    msg->version = 0;
}

// Core send_sync function - dispatches IPC messages
void send_sync(d3_saved *saved, uint64_t buffer, uint32_t handle, const char *name) {
    printf("[IPC] %s: buffer=%#lx handle=%#x\n", name, buffer, handle);

    // Try to parse the message
    cmif_header *msg = (cmif_header *)buffer;
    if (message_parse(msg, 0x1000) == 0) {
        printf("[IPC] Message parsed successfully\n");
        // Route to appropriate handler
        message_build_response(msg, 0);
    }

    // Set return values
    saved->x[0] = 0;  // Success
}

// SVC #0x21 - SendSyncRequest (x0 = absolute address)
void d3_svc_send_sync_request(d3_saved *saved) {
    uint64_t buffer = saved->x[0];      // Absolute address
    uint32_t handle = (uint32_t)saved->x[2];

    printf("[SVC21] SendSyncRequest: buffer=%#lx handle=%#x\n", buffer, handle);

    send_sync(saved, buffer, handle, "SendSyncRequest");
}

// SVC #0x22 - SendSyncRequestWithUserBuffer (x0 = TLR offset) ⭐ CRITICAL FIX
void d3_svc_send_sync_request_with_user(d3_saved *saved) {
    uint64_t offset = saved->x[0];      // Offset from TLR base (NOT absolute!)
    uint32_t handle = (uint32_t)saved->x[2];

    // ⭐ CRITICAL FIX: Get TLR from g_table directly
    // Previous bug: d3_tls_region() returned 0
    // Fix: Use g_table[D3_HOST_OFF_TLR / 8] instead
    uint64_t tlr = g_table[D3_HOST_OFF_TLR / 8];
    uint64_t buffer = tlr + offset;

    printf("[SVC22] SendSyncRequestWithUserBuffer:\n");
    printf("  offset=%#lx (from x0)\n", offset);
    printf("  tlr=%#lx (from g_table)\n", tlr);
    printf("  buffer=%#lx (calculated)\n", buffer);
    printf("  handle=%#x\n", handle);

    if (tlr == 0) {
        printf("[SVC22] ERROR: TLR is 0! Buffer will be invalid\n");
        printf("[SVC22] buffer will = %#lx (same as offset)\n", buffer);
    }

    send_sync(saved, buffer, handle, "SendSyncRequestWithUserBuffer");
}
