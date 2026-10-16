// d3_service.h - Service handler declarations
#ifndef D3_SERVICE_H
#define D3_SERVICE_H

#include <stdint.h>
#include "guest_layout.h"

// SVC (System Call) handlers
void d3_svc_send_sync_request_user(void *saved);
void d3_svc_send_sync_request(void *saved);
void d3_svc_get_thread_id(void *saved);

// HLE dispatch
int d3_hle_dispatch(d3_saved *saved, int kind, int extra);

// Signal handlers
void handle_sigsegv(int sig, siginfo_t *info, void *ctx);

// Helper functions
int safe_read(uint64_t addr, void *buf, size_t size);
void send_sync(void *saved, uint64_t buffer, uint32_t handle, const char *name);

// Table management
void d3_table_init(uint64_t tlr_base);
uint64_t d3_get_tlr(void);
void d3_set_tlr(uint64_t tlr);

#endif // D3_SERVICE_H
