#include "scene_pixels.h"
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <unistd.h>
#include <android/log.h>
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/vulkan_common/vulkan_memory_allocator.h"

namespace D3 {
namespace {
FILE* PixelFile() {
    static const std::string directory = [] {
        const char* path = std::getenv("D3_SCENE_TRACE_FILE");
        if (!path || !*path) return std::string{};
        const std::string trace_path(path);
        const auto slash = trace_path.find_last_of('/');
        return slash == std::string::npos ? std::string{} : trace_path.substr(0, slash + 1);
    }();
    if (directory.empty() || access((directory + "profile-scene-pixels").c_str(), F_OK) != 0) return nullptr;
    static FILE* file = std::fopen((directory + "scene-pixels.jsonl").c_str(), "w");
    return file;
}
}

void TraceScenePixels(Vulkan::MemoryAllocator& allocator, Vulkan::Scheduler& scheduler,
                      std::span<const ScenePixelImage> images, std::uint64_t draw, bool fp16) {
    if (draw > 8 && draw % 600 != 0) return;
    FILE* file = PixelFile();
    if (!file || images.empty()) return;
    constexpr unsigned columns = 16, rows = 9, pixels = columns * rows;
    const VkDeviceSize size = images.size() * pixels * 4;
    const VkBufferCreateInfo buffer_info{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .pNext = nullptr, .flags = 0, .size = size,
        .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .queueFamilyIndexCount = 0, .pQueueFamilyIndices = nullptr,
    };
    auto buffer = allocator.CreateBuffer(buffer_info, Vulkan::MemoryUsage::Download);
    const VkBuffer handle = *buffer;
    const std::vector<ScenePixelImage> sources(images.begin(), images.end());
    scheduler.RequestOutsideRenderPassOperationContext();
    scheduler.Record([=](Vulkan::vk::CommandBuffer command) {
        for (std::size_t index = 0; index < sources.size(); ++index) {
            const auto& source = sources[index];
            VkImageMemoryBarrier barrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .pNext = nullptr,
                .srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT,
                .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = source.image,
                .subresourceRange{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT,
                    .baseMipLevel = 0, .levelCount = 1, .baseArrayLayer = 0, .layerCount = 1},
            };
            const std::array<VkImageMemoryBarrier, 1> before{barrier};
            command.PipelineBarrier(VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                                    VK_PIPELINE_STAGE_TRANSFER_BIT, 0, {}, {}, before);
            std::array<VkBufferImageCopy, pixels> regions{};
            for (unsigned y = 0; y < rows; ++y) {
                for (unsigned x = 0; x < columns; ++x) {
                    const unsigned sample = y * columns + x;
                    regions[sample] = VkBufferImageCopy{
                        .bufferOffset = (index * pixels + sample) * 4,
                        .bufferRowLength = 0, .bufferImageHeight = 0,
                        .imageSubresource{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT,
                            .mipLevel = 0, .baseArrayLayer = 0, .layerCount = 1},
                        .imageOffset{.x = static_cast<int>((2 * x + 1) * source.extent.width / (2 * columns)),
                                     .y = static_cast<int>((2 * y + 1) * source.extent.height / (2 * rows)), .z = 0},
                        .imageExtent{1, 1, 1},
                    };
                }
            }
            command.CopyImageToBuffer(source.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                                      handle, regions);
            barrier.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
            barrier.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
            barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
            barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
            const std::array<VkImageMemoryBarrier, 1> after{barrier};
            command.PipelineBarrier(VK_PIPELINE_STAGE_TRANSFER_BIT,
                                    VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, {}, {}, after);
        }
        const VkMemoryBarrier host_barrier{
            .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .pNext = nullptr,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT,
        };
        const std::array<VkMemoryBarrier, 1> barriers{host_barrier};
        command.PipelineBarrier(VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                                0, barriers, {}, {});
    });
    // This synchronization is intentionally restricted to diagnostic captures.
    scheduler.Finish();
    buffer.Invalidate();
    const auto mapped = buffer.Mapped();
    for (std::size_t index = 0; index < sources.size(); ++index) {
        std::array<unsigned, 4> sums{}, maximum{}, minimum{255, 255, 255, 255};
        unsigned nonblack = 0, nonzero_alpha = 0;
        for (unsigned sample = 0; sample < pixels; ++sample) {
            const auto* rgba = mapped.data() + (index * pixels + sample) * 4;
            for (unsigned channel = 0; channel < 4; ++channel) {
                sums[channel] += rgba[channel];
                minimum[channel] = std::min<unsigned>(minimum[channel], rgba[channel]);
                maximum[channel] = std::max<unsigned>(maximum[channel], rgba[channel]);
            }
            nonblack += rgba[0] > 3 || rgba[1] > 3 || rgba[2] > 3;
            nonzero_alpha += rgba[3] != 0;
        }
        const auto& source = sources[index];
        std::fprintf(file,
            "{\"draw\":%llu,\"stage\":\"%s\",\"fp16\":%s,\"extent\":[%u,%u],"
            "\"pixels\":%u,\"nonblack\":%u,\"nonzero_alpha\":%u,"
            "\"min\":[%u,%u,%u,%u],\"max\":[%u,%u,%u,%u],\"mean\":[%g,%g,%g,%g]}\n",
            static_cast<unsigned long long>(draw), source.label, fp16 ? "true" : "false",
            source.extent.width, source.extent.height, pixels, nonblack, nonzero_alpha,
            minimum[0], minimum[1], minimum[2], minimum[3], maximum[0], maximum[1], maximum[2], maximum[3],
            double(sums[0]) / pixels, double(sums[1]) / pixels, double(sums[2]) / pixels, double(sums[3]) / pixels);
        __android_log_print(ANDROID_LOG_INFO, "d3gpu", "scene-pixels draw=%llu stage=%s nonblack=%u/%u fp16=%d",
            static_cast<unsigned long long>(draw), source.label, nonblack, pixels, fp16);
    }
    std::fflush(file);
}
}
