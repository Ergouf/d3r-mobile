/* Restored declarations for the recovered host/service implementation. */
#ifndef D3_SERVICE_H
#define D3_SERVICE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "d3_host.h"

#define D3_HANDLE_FIRST UINT32_C(0x1000)
#define D3_HANDLE_CURRENT_PROCESS UINT32_C(0xffff8001)
#define D3_HANDLE_CURRENT_THREAD UINT32_C(0xffff8000)
#define D3_LOCAL_SAVE_ROOT D3_DATA_ROOT "/saves/1-0000000000000000-4433484f53545531-4c4f43414c555345-0000000000000000-00000001"

enum {
    D3_OBJ_NONE = 0,
    D3_OBJ_PROCESS = 1,
    D3_OBJ_THREAD = 2,
    D3_OBJ_SESSION = 3,
    D3_OBJ_EVENT = 4,
    D3_OBJ_TRANSFER_MEM = 5,
    D3_OBJ_CODE_MEM = 6,
    D3_OBJ_SHARED_MEM = 7
};

uint32_t d3_handle_alloc(int kind, const char *name, uint64_t arg);
int d3_handle_kind(uint32_t handle);
const char *d3_handle_name(uint32_t handle);
uint64_t d3_handle_arg(uint32_t handle);
uint32_t d3_handle_domain_key(uint32_t handle);
void d3_handle_set_arg(uint32_t handle, uint64_t arg);
int d3_handle_close(uint32_t handle);
void d3_handle_dump(void);

void d3_service_open(void);

/* Result word of the most recent CMIF reply; the abort diagnostics print it next
   to the failing nn::Result slots so a bad reply is recognisable. */
uint32_t d3_service_last_result(void);
/* Message buffer of the most recent SendSyncRequest: the hid probes print it
   to show what the SDK's reply path left in it. */
uint64_t d3_service_current_buffer(void);
/* Fill the Npad section of nn::hid's shared memory once the title mapped it. */
void d3_hid_seed(uint64_t address);
void d3_hid_map(uint64_t address, uint64_t writable_alias);
void d3_hid_unmap(uint64_t address);
void d3_hid_update(uint64_t buttons, int32_t lx, int32_t ly, int32_t rx, int32_t ry);
void d3_service_dump(const char *what, uint64_t address, const void *data, size_t size);
void d3_svc_connect_to_named_port(d3_saved *saved);
void d3_svc_send_sync_request(d3_saved *saved, uint64_t tls);
void d3_svc_send_sync_request_user(d3_saved *saved);
void d3_svc_send_async_request(d3_saved *saved);

#endif
