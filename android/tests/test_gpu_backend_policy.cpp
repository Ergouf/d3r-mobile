#include "../gpu/host/gpu_backend_policy.h"
#include <cassert>
#include <cstdio>

int main() {
    assert(d3_gpu_backend_request(nullptr) == D3_GPU_BACKEND_EDEN);
    assert(d3_gpu_backend_request("") == D3_GPU_BACKEND_EDEN);
    assert(d3_gpu_backend_request("eden") == D3_GPU_BACKEND_EDEN);
    assert(d3_gpu_backend_request("s2arm-nvn") == D3_GPU_BACKEND_S2ARM_NVN);
    assert(d3_gpu_backend_request("s2arm") == D3_GPU_BACKEND_UNKNOWN);
    assert(d3_gpu_backend_request("turnip") == D3_GPU_BACKEND_UNKNOWN);
    assert(d3_gpu_backend_request("EDEN") == D3_GPU_BACKEND_UNKNOWN);
    std::puts("gpu backend request policy: ok");
    return 0;
}
