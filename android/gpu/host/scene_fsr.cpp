#include "scene_fsr.h"
#include "scene_policy.h"
#include "scene_region.h"
#include "scene_pixels.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <string>
#include <unistd.h>
#include <android/log.h>
#include "common/settings.h"
#include "video_core/memory_manager.h"
#include "video_core/renderer_vulkan/blit_image.h"
#include "video_core/renderer_vulkan/present/fsr.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace D3 {
namespace {
bool scene_enabled{};
std::uint32_t scene_width{1280};

FILE* TraceFile() {
    static FILE* file = [] {
        const char* path = std::getenv("D3_SCENE_TRACE_FILE");
        return path && *path ? std::fopen(path, "w") : nullptr;
    }();
    return file;
}

struct SceneExperiment {
    bool use_fsr{};
    bool force_fp32{};
    bool easu_only{};
    Vulkan::FSR::Probe probe{Vulkan::FSR::Probe::Disabled};
};
SceneExperiment ReadSceneExperiment() {
    static const std::string directory = [] {
        const char* path = std::getenv("D3_SCENE_TRACE_FILE");
        if (!path || !*path) return std::string{};
        const std::string trace(path);
        const auto slash = trace.find_last_of('/');
        return slash == std::string::npos ? std::string{} : trace.substr(0, slash + 1);
    }();
    static SceneExperiment mode;
    static unsigned checks{};
    if (++checks % 32 != 1) return mode;
    if (!directory.empty()) {
        mode.use_fsr = access((directory + "profile-scene-fsr").c_str(), F_OK) == 0 &&
                       access((directory + "profile-scene-passthrough").c_str(), F_OK) != 0;
        mode.force_fp32 = access((directory + "profile-scene-fsr-fp32").c_str(), F_OK) == 0;
        mode.easu_only = access((directory + "profile-scene-fsr-easu").c_str(), F_OK) == 0;
        mode.probe = access((directory + "profile-scene-fsr-solid").c_str(), F_OK) == 0
            ? Vulkan::FSR::Probe::Solid
            : access((directory + "profile-scene-fsr-copy").c_str(), F_OK) == 0
                ? Vulkan::FSR::Probe::Sample : Vulkan::FSR::Probe::Disabled;
        if (mode.probe != Vulkan::FSR::Probe::Disabled) {
            mode.force_fp32 = true;
            mode.easu_only = true;
        }
    } else {
        const char* fsr = std::getenv("D3_SCENE_USE_FSR");
        const char* passthrough = std::getenv("D3_SCENE_PASSTHROUGH");
        const char* stage = std::getenv("D3_SCENE_FSR_STAGE");
        mode.use_fsr = fsr && *fsr && !(passthrough && *passthrough);
        mode.easu_only = stage && std::strcmp(stage, "easu") == 0;
    }
    return mode;
}
}

void ConfigureSceneMode(bool enabled, std::uint32_t guest_width) {
    scene_enabled = enabled;
    scene_width = guest_width * 4 / 5;
    __android_log_print(ANDROID_LOG_INFO, "d3gpu",
        "scene-fsr mode=%d scene=%ux720 scale=%.4f UI=%ux900 scale=1", enabled, scene_width,
        Settings::values.resolution_info.up_factor, guest_width);
}
bool SceneModeEnabled() { return scene_enabled; }
bool IsSceneTarget(std::uint32_t width, std::uint32_t height) {
    return width == scene_width && height == 720;
}

void TraceSceneDraw(std::uint64_t vs, std::uint64_t fs, Vulkan::TextureCache& cache,
                    Tegra::Engines::Maxwell3D& engine, Tegra::MemoryManager& memory,
                    std::span<const VideoCommon::ImageViewInOut> views) {
    FILE* file = TraceFile();
    if (!file) return;
    const auto& rt = cache.SceneRenderTargets();
    const auto& regs = engine.regs;
    // Record new shader/attachment combinations, rather than logging every frame.
    static std::unordered_set<std::uint64_t> seen;
    const std::uint64_t signature = vs ^ (fs << 7) ^ rt.color_buffer_ids[0].index ^
        (std::uint64_t(rt.size.width) << 32) ^ (std::uint64_t(rt.size.height) << 48) ^
        (std::uint64_t(cache.IsRescaling()) << 63);
    if (seen.size() >= 8192 || !seen.insert(signature).second) return;
    const auto physical_area = cache.GetFramebuffer()->RenderArea();
    const auto& vp = regs.viewport_transform[0];
    const auto& state = engine.draw_manager.draw_state;
    std::fprintf(file, "{\"kind\":\"draw\",\"vs\":\"%016llx\",\"fs\":\"%016llx\","
        "\"scaled\":%d,\"framebuffer\":[%u,%u],\"clip\":[%u,%u],\"topology\":%u,"
        "\"indexed\":%d,\"vertices\":%u,\"indices\":%u,\"viewport\":[%g,%g,%g,%g],\"targets\":[",
        (unsigned long long)vs, (unsigned long long)fs, cache.IsRescaling(),
        physical_area.width, physical_area.height, regs.surface_clip.width, regs.surface_clip.height,
        unsigned(state.topology), state.draw_indexed, state.vertex_buffer.count, state.index_buffer.count,
        vp.translate_x, vp.translate_y, vp.scale_x, vp.scale_y);
    bool first = true;
    for (const auto id : rt.color_buffer_ids) {
        if (!id || id == VideoCommon::NULL_IMAGE_VIEW_ID) continue;
        const auto& view = cache.GetImageView(id);
        std::fprintf(file, "%s[%u,%u,%u,%d]", first ? "" : ",", view.size.width,
                     view.size.height, unsigned(view.format), view.IsRescaled());
        first = false;
    }
    std::fprintf(file, "],\"depth\":[");
    if (rt.depth_buffer_id && rt.depth_buffer_id != VideoCommon::NULL_IMAGE_VIEW_ID) {
        const auto& view = cache.GetImageView(rt.depth_buffer_id);
        std::fprintf(file, "%u,%u,%d", view.size.width, view.size.height, view.IsRescaled());
    }
    std::fprintf(file, "],\"textures\":[");
    first = true;
    for (const auto& item : views) {
        if (!item.id || item.id == VideoCommon::NULL_IMAGE_VIEW_ID) continue;
        const auto& view = cache.GetImageView(item.id);
        std::fprintf(file, "%s[%u,%u,%u,%d]", first ? "" : ",", view.size.width,
                     view.size.height, unsigned(view.format), view.IsRescaled());
        first = false;
    }
    if (IsSceneCompositor(vs, fs)) {
        const auto& cb = engine.state.shader_stages[4].const_buffers[3];
        if (cb.enabled && cb.size >= 0x690) {
            std::array<float, 4> uv{}, size{};
            memory.ReadBlockUnsafe(cb.address + 0x430, uv.data(), sizeof uv);
            memory.ReadBlockUnsafe(cb.address + 0x680, size.data(), sizeof size);
            std::fprintf(file, "],\"uv\":[%g,%g,%g,%g],\"source_size\":[%g,%g,%g,%g]}",
                uv[0], uv[1], uv[2], uv[3], size[0], size[1], size[2], size[3]);
        } else std::fprintf(file, "]}");
    } else std::fprintf(file, "]}");
    std::fputc('\n', file);
    std::fflush(file);
}

struct SceneFSR::Impl {
    struct Target {
        std::array<std::unique_ptr<Vulkan::FSR>, 2> fsr;
        std::array<std::uint64_t, 3> ticks{};
        std::size_t next{};
    };
    std::unordered_map<std::uint64_t, Target> targets;
    std::uint64_t draws{};
};
SceneFSR::SceneFSR() : impl(std::make_unique<Impl>()) {}
SceneFSR::~SceneFSR() = default;

bool SceneFSR::Draw(const Vulkan::Device& device, Vulkan::MemoryAllocator& allocator,
                    Vulkan::Scheduler& scheduler, Vulkan::BlitImageHelper& blitter,
                    Vulkan::TextureCache& cache, Tegra::Engines::Maxwell3D& engine,
                    Tegra::MemoryManager& memory, VideoCommon::ImageViewId source_id,
                    const VkViewport& viewport, const VkRect2D& scissor, bool is_indexed) {
    using namespace VideoCommon;
    if (!SceneModeEnabled() || !source_id || source_id == NULL_IMAGE_VIEW_ID) return false;
    const auto& state = engine.draw_manager.draw_state;
    const auto& regs = engine.regs;
    const auto& rt = cache.SceneRenderTargets();
    const u32 draw_count = state.draw_indexed ? state.index_buffer.count
                                                               : state.vertex_buffer.count;
    if (draw_count != 3 || (unsigned(state.topology) != 4 && unsigned(state.topology) != 5) ||
        rt.depth_buffer_id || cache.IsRescaling() || !rt.color_buffer_ids[0] ||
        regs.blend.enable[0] || regs.rt_control.Map(0) != 0 || regs.transform_feedback_enabled) return false;
    for (std::size_t n = 1; n < rt.color_buffer_ids.size(); ++n)
        if (rt.color_buffer_ids[n]) return false;
    const auto& source = cache.GetImageView(source_id);
    auto& dest = cache.GetImageView(rt.color_buffer_ids[0]);
    if (!source.IsRescaled() || source.image_id == dest.image_id ||
        !IsSceneTarget(source.size.width, source.size.height) ||
        source.type != ImageViewType::e2D || source.range.base.level != 0 || source.range.base.layer != 0 ||
        source.range.extent.layers != 1 || source.range.extent.levels != 1 ||
        source.Samples() != VK_SAMPLE_COUNT_1_BIT ||
        dest.Samples() != VK_SAMPLE_COUNT_1_BIT ||
        VideoCore::Surface::GetFormatType(source.format) != VideoCore::Surface::SurfaceType::ColorTexture ||
        VideoCore::Surface::GetFormatType(dest.format) != VideoCore::Surface::SurfaceType::ColorTexture ||
        VideoCore::Surface::IsPixelFormatInteger(source.format) ||
        VideoCore::Surface::IsPixelFormatInteger(dest.format) ||
        dest.size.width <= source.size.width || dest.size.height <= source.size.height ||
        std::uint64_t(dest.size.width) * source.size.height !=
            std::uint64_t(dest.size.height) * source.size.width) return false;
    const auto& cb = engine.state.shader_stages[4].const_buffers[3];
    if (!cb.enabled || cb.size < 0x690) return false;
    std::array<float, 4> uv{}, logical_size{};
    memory.ReadBlockUnsafe(cb.address + 0x430, uv.data(), sizeof uv);
    memory.ReadBlockUnsafe(cb.address + 0x680, logical_size.data(), sizeof logical_size);
    if (logical_size[0] != source.size.width || logical_size[1] != source.size.height) return false;
    const auto& resolution = Settings::values.resolution_info;
    const VkExtent2D input{resolution.ScaleUp(source.size.width), resolution.ScaleUp(source.size.height)};
    auto region = MakeSceneRegion(uv, {viewport.x, viewport.y, viewport.width, viewport.height},
        {scissor.offset.x, scissor.offset.y, scissor.extent.width, scissor.extent.height},
        {input.width, input.height}, {rt.size.width, rt.size.height});
    if (!region || !source.size.width || !source.size.height) return false;
    // Guest viewport registers address the unscaled logical surface. The compositor
    // target can have a larger host extent, so map the scene rectangle into that target.
    const double scale_x = static_cast<double>(rt.size.width) / source.size.width;
    const double scale_y = static_cast<double>(rt.size.height) / source.size.height;
    for (std::size_t n = 0; n < region->output.size(); ++n) {
        const double scale = n < 2 ? scale_x : scale_y;
        region->output[n] = static_cast<int>(std::llround(region->output[n] * scale));
    }
    if (region->output[0] < 0 || region->output[1] < 0 || region->output[2] <= 0 ||
        region->output[3] <= 0 ||
        std::uint32_t(region->output[0] + region->output[2]) > rt.size.width ||
        std::uint32_t(region->output[1] + region->output[3]) > rt.size.height) return false;
    const auto& out = region->output;
    const VkExtent2D output{std::uint32_t(out[2]), std::uint32_t(out[3])};
    const auto experiment = ReadSceneExperiment();
    const bool use_fsr = experiment.use_fsr;
    const std::uint64_t key = (std::uint64_t(output.width) << 32) | output.height;
    auto it = impl->targets.find(key);
    if (it == impl->targets.end()) {
        // Keep all cached sizes alive until RasterizerVulkan's destructor finishes the GPU.
        if (impl->targets.size() >= 8) return false;
        Impl::Target target;
        it = impl->targets.emplace(key, std::move(target)).first;
    }
    auto& target = it->second;
    auto& fsr = target.fsr[experiment.force_fp32 ? 1 : 0];
    if (use_fsr && !fsr) {
        fsr = std::make_unique<Vulkan::FSR>(device, allocator, 3, output, experiment.force_fp32);
    }
    const auto slot = target.next++ % target.ticks.size();
    if (target.ticks[slot]) scheduler.Wait(target.ticks[slot]);
    const auto report = [&](const char* mode) {
        ++impl->draws;
        if (impl->draws > 8 && impl->draws % 300 != 0) return;
        __android_log_print(ANDROID_LOG_INFO, "d3gpu",
            "scene-%s draw=%llu input=%ux%u crop=%.4f,%.4f,%.4f,%.4f output=%d,%d,%dx%d ui=%ux%u",
            mode, (unsigned long long)impl->draws, input.width, input.height,
            uv[1], uv[3], uv[0], uv[2], out[0], out[1], out[2], out[3],
            rt.size.width, rt.size.height);
        if (FILE* file = TraceFile()) {
            std::fprintf(file, "{\"kind\":\"%s\",\"draw\":%llu,\"input\":[%u,%u],"
                "\"crop\":[%g,%g,%g,%g],\"output\":[%d,%d,%d,%d],\"ui\":[%u,%u]}\n",
                mode, (unsigned long long)impl->draws,
                input.width, input.height, uv[1], uv[3], uv[0], uv[2],
                out[0], out[1], out[2], out[3], rt.size.width, rt.size.height);
            std::fflush(file);
        }
    };
    VkImage image{};
    if (use_fsr) {
        // FSR samples the guest colour attachment right after the guest finished
        // writing it. End the guest render pass before making those writes visible.
        scheduler.RequestOutsideRenderPassOperationContext();
        const VkImage fsr_source = source.ImageHandle();
        scheduler.Record([=](Vulkan::vk::CommandBuffer command) {
            const std::array<VkImageMemoryBarrier, 1> barrier{{
                {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .pNext = nullptr,
                 .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                                  VK_ACCESS_TRANSFER_WRITE_BIT | VK_ACCESS_SHADER_WRITE_BIT,
                 .dstAccessMask = VK_ACCESS_SHADER_READ_BIT,
                 .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                 .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                 .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                 .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = fsr_source,
                 .subresourceRange{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .baseMipLevel = 0,
                                   .levelCount = 1, .baseArrayLayer = 0, .layerCount = 1}},
            }};
            command.PipelineBarrier(VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                                    VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, 0, {}, {}, barrier);
        });
        const Common::Rectangle<float> crop{region->crop[0], region->crop[1],
                                            region->crop[2], region->crop[3]};
        fsr->Draw(device, scheduler, slot, source.ImageHandle(),
                         source.Handle(Shader::TextureType::Color2D), input, crop, experiment.probe);
        image = experiment.easu_only ? fsr->StageImage(slot, 0) : fsr->OutputImage(slot);
    } else {
        image = source.ImageHandle();
    }
    // Vivo's implicit GameLib VSR layer crashes when host code opens a render pass or
    // pushes descriptors while compositing into a guest image, so the composite stays a
    // transfer-only blit that avoids both interception points.
    const VkImage target_image = dest.ImageHandle();
    const std::array<int, 4> source_rect = use_fsr
        ? std::array<int, 4>{0, 0, static_cast<int>(output.width), static_cast<int>(output.height)}
        : region->source;
    const std::array<VkOffset3D, 2> src_offsets{{
        {.x = source_rect[0], .y = source_rect[1], .z = 0},
        {.x = source_rect[2], .y = source_rect[3], .z = 1},
    }};
    const std::array<VkOffset3D, 2> dst_offsets{{
        {.x = out[0], .y = out[1], .z = 0},
        {.x = out[0] + out[2], .y = out[1] + out[3], .z = 1},
    }};
    const VkImageBlit blit_region{
        .srcSubresource{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .mipLevel = 0,
                        .baseArrayLayer = 0, .layerCount = 1},
        .srcOffsets = {src_offsets[0], src_offsets[1]},
        .dstSubresource{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .mipLevel = 0,
                        .baseArrayLayer = 0, .layerCount = 1},
        .dstOffsets = {dst_offsets[0], dst_offsets[1]},
    };
    scheduler.RequestOutsideRenderPassOperationContext();
    scheduler.Record([=](Vulkan::vk::CommandBuffer command) {
        const std::array<VkImageMemoryBarrier, 2> before{{
            {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .pNext = nullptr,
             .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                              VK_ACCESS_TRANSFER_WRITE_BIT | VK_ACCESS_SHADER_WRITE_BIT,
             .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
             .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
             .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
             .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
             .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = image,
             .subresourceRange{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .baseMipLevel = 0,
                               .levelCount = 1, .baseArrayLayer = 0, .layerCount = 1}},
            {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .pNext = nullptr,
             .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                              VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT,
             .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
             .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
             .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
             .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
             .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = target_image,
             .subresourceRange{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .baseMipLevel = 0,
                               .levelCount = 1, .baseArrayLayer = 0, .layerCount = 1}},
        }};
        command.PipelineBarrier(VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                                VK_PIPELINE_STAGE_TRANSFER_BIT, 0, {}, {}, before);
        const std::array<VkImageBlit, 1> regions{blit_region};
        command.BlitImage(image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, target_image,
                          VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, regions, VK_FILTER_LINEAR);
        const std::array<VkImageMemoryBarrier, 2> after{{
            {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .pNext = nullptr,
             .srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT, .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT,
             .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
             .newLayout = VK_IMAGE_LAYOUT_GENERAL,
             .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
             .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = image,
             .subresourceRange{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .baseMipLevel = 0,
                               .levelCount = 1, .baseArrayLayer = 0, .layerCount = 1}},
            {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .pNext = nullptr,
             .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
             .dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_MEMORY_READ_BIT,
             .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
             .newLayout = VK_IMAGE_LAYOUT_GENERAL,
             .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
             .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = target_image,
             .subresourceRange{.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .baseMipLevel = 0,
                               .levelCount = 1, .baseArrayLayer = 0, .layerCount = 1}},
        }};
        command.PipelineBarrier(VK_PIPELINE_STAGE_TRANSFER_BIT,
                                VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, {}, {}, after);
    });
    scheduler.InvalidateState();
    target.ticks[slot] = scheduler.CurrentTick();
    report(use_fsr ? (experiment.probe == Vulkan::FSR::Probe::Solid ? "solid" :
                     experiment.probe == Vulkan::FSR::Probe::Sample ? "copy" :
                     experiment.easu_only ? "easu" : "fsr") : "bilinear");
    if (source.format == VideoCore::Surface::PixelFormat::A8B8G8R8_UNORM &&
        dest.format == VideoCore::Surface::PixelFormat::A8B8G8R8_UNORM) {
        std::array<ScenePixelImage, 4> images{};
        std::size_t count = 0;
        images[count++] = {"input", source.ImageHandle(), input};
        if (use_fsr) {
            images[count++] = {"easu", fsr->StageImage(slot, 0), output};
            images[count++] = {"rcas", fsr->OutputImage(slot), output};
        }
        images[count++] = {"composited", target_image, {rt.size.width, rt.size.height}};
        TraceScenePixels(allocator, scheduler, std::span(images.data(), count),
                          impl->draws, use_fsr && device.IsFloat16Supported() && !experiment.force_fp32);
    }
    return true;
}
}
