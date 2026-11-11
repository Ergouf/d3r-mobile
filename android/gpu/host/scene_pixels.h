#pragma once
#include <cstdint>
#include <span>
#include <vulkan/vulkan.h>

namespace Vulkan {
class MemoryAllocator;
class Scheduler;
}

namespace D3 {
struct ScenePixelImage {
    const char* label;
    VkImage image;
    VkExtent2D extent;
};

// Diagnostic readback of RGBA8 images, enabled only by profile-scene-pixels.
void TraceScenePixels(Vulkan::MemoryAllocator& allocator, Vulkan::Scheduler& scheduler,
                      std::span<const ScenePixelImage> images, std::uint64_t draw, bool fp16);
}
