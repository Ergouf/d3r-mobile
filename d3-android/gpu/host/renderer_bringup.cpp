// Instantiate Eden's Vulkan renderer against the Android surface.
//
// This is the step between the hand-written clear (M1) and the real renderer:
// once this succeeds, framebuffer composites from the guest can go through
// Vulkan::RendererVulkan instead of the temporary clear path.
#include <android/log.h>

#include <cstdarg>
#include <exception>
#include <memory>

#include "core/core.h"
#include "emu_window_d3.h"
#include "video_core/gpu.h"
#include "video_core/host1x/host1x.h"
#include "video_core/control/channel_state.h"
#include "video_core/memory_manager.h"
#include "video_core/renderer_vulkan/renderer_vulkan.h"

namespace {

void RendererReport(const char* format, ...) {
    va_list args;
    va_start(args, format);
    __android_log_vprint(ANDROID_LOG_INFO, "d3gpu", format, args);
    va_end(args);
}

std::unique_ptr<Core::System> g_system;
std::unique_ptr<D3::EmuWindowD3> g_window;
std::unique_ptr<Tegra::MemoryManager> g_address_space;

} // namespace

// Exercises the GPU command pipeline without a guest: allocate a channel and
// initialise it.  Proves the GPU thread, engines and rasterizer binding are
// live after RendererVulkan is attached.
extern "C" __attribute__((visibility("default"))) int d3_gpu_channel_test(void) {
    if (!g_system) {
        RendererReport("channel: renderer not initialised");
        return -1;
    }
    try {
        // nvhost_as_gpu::BindChannel wires the channel to the address space the
        // guest allocated; a channel cannot be initialised without it.
        if (!g_address_space) {
            g_address_space = std::make_unique<Tegra::MemoryManager>(*g_system);
            g_system->GPU().InitAddressSpace(*g_address_space);
        }
        auto channel = g_system->GPU().AllocateChannel();
        if (!channel) {
            RendererReport("channel: AllocateChannel returned null");
            return -2;
        }
        channel->memory_manager = g_address_space.get();
        g_system->GPU().InitChannel(*channel, 0);
        RendererReport("channel: allocated and initialised (%p)", static_cast<void*>(channel.get()));
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("channel: failed: %s", exception.what());
        return -3;
    }
}

extern "C" __attribute__((visibility("default"))) int d3_gpu_renderer_init(void* native_window) {
    if (!native_window) {
        RendererReport("renderer: no window");
        return -1;
    }
    if (g_window) {
        return 0;
    }

    try {
        g_system = std::make_unique<Core::System>();
        g_window = std::make_unique<D3::EmuWindowD3>(static_cast<ANativeWindow*>(native_window));

        auto& gpu = g_system->GPU();
        auto& host1x = g_system->Host1x();
        auto renderer = std::make_unique<Vulkan::RendererVulkan>(*g_window, host1x.memory_manager,
                                                                 gpu, g_window->CreateSharedContext());
        const std::string vendor = renderer->GetDeviceVendor();
        gpu.BindRenderer(std::move(renderer));
        RendererReport("renderer: Vulkan::RendererVulkan ready (vendor=%s)", vendor.c_str());
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("renderer: failed: %s", exception.what());
        return -2;
    } catch (...) {
        RendererReport("renderer: failed with an unknown error");
        return -3;
    }
}
