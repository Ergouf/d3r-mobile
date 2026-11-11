#pragma once
#include <memory>
#include <span>
#include "video_core/renderer_vulkan/vk_texture_cache.h"
#include "video_core/engines/maxwell_3d.h"
namespace D3 {
void TraceSceneDraw(std::uint64_t vs, std::uint64_t fs, Vulkan::TextureCache& cache,
                    Tegra::Engines::Maxwell3D& engine, Tegra::MemoryManager& memory,
                    std::span<const VideoCommon::ImageViewInOut> views);
class SceneFSR {
public:
    SceneFSR();
    ~SceneFSR();
    bool Draw(const Vulkan::Device& device, Vulkan::MemoryAllocator& allocator,
              Vulkan::Scheduler& scheduler, Vulkan::BlitImageHelper& blitter,
              Vulkan::TextureCache& cache, Tegra::Engines::Maxwell3D& engine,
              Tegra::MemoryManager& memory, VideoCommon::ImageViewId source_id,
              const VkViewport& viewport, const VkRect2D& scissor, bool is_indexed);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
}
