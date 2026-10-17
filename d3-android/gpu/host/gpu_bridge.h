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

#ifdef __cplusplus
}
#endif
