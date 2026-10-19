// C ABI for the GPU bridge.
//
// The host side (d3_host.c / d3_service.c) is C and owns the nvdrv services.
// Everything Eden is C++, so the two meet here: each entry point takes plain
// integers and pointers, never a C++ type.
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/// Brings up renderer + address space + one GPU channel.  Returns 0 on success.
int d3_gpu_bridge_start(void* native_window);

/// Returns the bound channel id, or a negative value when the bridge is down.
int d3_gpu_bridge_channel_id(void);
void *d3_gpu_guest_heap(uint64_t *size);
uint32_t d3_gpu_nv_as_create(uint32_t big_page);
uint32_t d3_gpu_nv_map(uint32_t space, uint64_t gpu_address, uint64_t cpu_address,
                      uint64_t size, uint32_t kind);
uint32_t d3_gpu_nv_unmap(uint32_t space, uint64_t gpu_address, uint64_t size);
uint32_t d3_gpu_nv_rekind(uint32_t space, uint64_t gpu_address, uint64_t offset,
                         uint64_t size, uint32_t kind);
void d3_gpu_nv_as_close(uint32_t space);
uint32_t d3_gpu_nv_channel_create(void);
uint32_t d3_gpu_nv_channel_bind(uint32_t channel, uint32_t space);
uint32_t d3_gpu_nv_channel_init(uint32_t channel);
void d3_gpu_nv_channel_close(uint32_t channel);
uint32_t d3_gpu_nv_submit(uint32_t channel, const uint64_t *entries, uint32_t count,
                         uint32_t flags, uint32_t wait_id, uint32_t wait_value, uint32_t signal_id);
void d3_gpu_nv_diagnostics(void);
int d3_gpu_present_guest(uint64_t address, uint64_t size, const uint32_t *buffer,
                         const uint32_t *queue_input);
int d3_gpu_import_framebuffer(uint64_t address, uint64_t size);
void d3_gpu_release_framebuffer(uint64_t address, uint64_t size);
void d3_gpu_set_cache_scan(int enabled);
void d3_gpu_notify_cpu_submission(void);
int d3_gpu_handle_cpu_write_fault(uint64_t address);
void d3_gpu_set_write_watch(int enabled);
void d3_gpu_cpu_memory_permission(uint64_t address, uint64_t size, int writable);
void d3_gpu_begin_cpu_write(uint64_t address, uint64_t size);
void d3_gpu_end_cpu_write(void);
int d3_gpu_cpu_memory_writable(uint64_t address);

#ifdef __cplusplus
}
#endif
