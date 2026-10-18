#ifndef D3_HOST_H
#define D3_HOST_H

#include "../guest_layout.h"

#ifndef D3_DATA_ROOT
#define D3_DATA_ROOT "/sdcard/D3"
#endif
#ifndef D3_PRIVATE_ROOT
#define D3_PRIVATE_ROOT "/data/data/com.d3mobile.host"
#endif

int d3_host_start(const char *guest_path);
/* thread_tp is the dispatching guest thread's tpidr_el0; the veneer passes it in
   x3 so the dispatcher never reads a shared table slot that another guest thread
   may be writing. */
void d3_hle_dispatch(uint32_t kind, uint64_t extra, d3_saved *saved, uint64_t thread_tp);
void d3_trace_guest(const char *tag, const d3_saved *saved);

#endif
