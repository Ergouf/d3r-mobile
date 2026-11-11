#include "../host/d3_host.h"

void d3_dump_sdk_global(uint64_t offset) {
    (void)offset;
}

void d3_watch_global(uint64_t offset, const char *why) {
    (void)offset;
    (void)why;
}

void d3_event_set(uint32_t handle, int signaled) {
    (void)handle;
    (void)signaled;
}

void d3_event_on_close(uint32_t handle) {
    (void)handle;
}
