// Single translation unit that compiles the Vulkan Memory Allocator.
// Eden's vulkan_common/vma.h only includes the header and expects the host to
// instantiate the implementation once (its Android JNI file does the same).
#define VMA_STATIC_VULKAN_FUNCTIONS 0
#define VMA_DYNAMIC_VULKAN_FUNCTIONS 1
#define VMA_IMPLEMENTATION
#include "vk_mem_alloc.h"
