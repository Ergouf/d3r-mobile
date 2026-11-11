#pragma once

#include <string.h>

/* S2Arm NVN has not been linked into the Eden GPU archive. Explicit requests
 * must fail, never silently fall back and mislabel power/performance tests. */
typedef enum D3GpuBackendRequest {
    D3_GPU_BACKEND_EDEN,
    D3_GPU_BACKEND_S2ARM_NVN,
    D3_GPU_BACKEND_UNKNOWN
} D3GpuBackendRequest;

static inline D3GpuBackendRequest d3_gpu_backend_request(const char *setting) {
    if (!setting || !*setting || strcmp(setting, "eden") == 0)
        return D3_GPU_BACKEND_EDEN;
    if (strcmp(setting, "s2arm-nvn") == 0)
        return D3_GPU_BACKEND_S2ARM_NVN;
    return D3_GPU_BACKEND_UNKNOWN;
}
