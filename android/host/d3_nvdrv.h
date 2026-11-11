#ifndef D3_NVDRV_H
#define D3_NVDRV_H

#include <stddef.h>
#include <stdint.h>

uint32_t d3_nv_open(uint32_t session, const char *path, uint32_t *descriptor);
uint32_t d3_nv_close(uint32_t session, uint32_t descriptor);
uint32_t d3_nv_buffer_pin(uint32_t id, uint64_t *address, uint64_t *size);
void d3_nv_buffer_unpin(uint32_t id);
uint32_t d3_nv_submit(uint32_t session, uint32_t descriptor, uint32_t *parameters,
                      const uint64_t *entries, size_t size);
uint32_t d3_nv_ioctl(uint32_t session, uint32_t descriptor, uint32_t command,
                     void *parameters, size_t size, void *inline_output, size_t inline_size);

#endif
