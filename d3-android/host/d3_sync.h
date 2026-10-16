#ifndef D3_SYNC_H
#define D3_SYNC_H

#include <stdint.h>

#define D3_SYNC_WAIT_MASK UINT32_C(0x40000000)
#define D3_SYNC_TIMED_OUT UINT32_C(0xea01)

uint32_t d3_sync_lock(uint32_t owner, uint32_t *mutex, uint32_t tag);
uint32_t d3_sync_unlock(uint32_t *mutex, uint32_t tag);
uint32_t d3_sync_wait(uint32_t *mutex, uint32_t *key, uint32_t tag, int64_t timeout);
uint32_t d3_sync_signal(uint32_t *key, int32_t count);

#endif
