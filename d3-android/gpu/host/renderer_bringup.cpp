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
#include "gpu_bridge.h"
#include "emu_window_d3.h"
#include "video_core/gpu.h"
#include "video_core/host1x/host1x.h"
#include "video_core/control/channel_state.h"
#include "video_core/dma_pusher.h"
#include "video_core/memory_manager.h"
#include "video_core/framebuffer_config.h"
#include "core/hle/service/nvnflinger/pixel_format.h"
#include "core/hle/service/nvnflinger/buffer_transform_flags.h"
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
std::shared_ptr<Tegra::Control::ChannelState> g_channel;

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
        g_channel = channel;
        RendererReport("channel: allocated and initialised (%p)", static_cast<void*>(channel.get()));

        // NOTE: GPU::PushGPUEntries(channel->bind_id, Tegra::CommandList{}) was
        // tried here; the call does not return on device (the GPU thread waits
        // for work that an empty list never delivers), so real pushbuffer
        // submission needs to come from the nvdrv path with actual commands.
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
        // BindRenderer only wires the renderer in; the GPU command thread is
        // started by GPU::Start(), otherwise submits queue up forever.
        gpu.Start();
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
extern "C" int d3_gpu_bridge_start(void* native_window) {
    const int renderer_status = d3_gpu_renderer_init(native_window);
    if (renderer_status != 0) {
        return renderer_status;
    }
    return d3_gpu_channel_test();
}

extern "C" int d3_gpu_bridge_channel_id(void) {
    return g_channel ? g_channel->bind_id : -1;
}
// Maps one page of process memory into the GPU address space and checks that
// the translated pointer aliases the same bytes.  This is the plumbing every
// pushbuffer and framebuffer read will use.
extern "C" int d3_gpu_bridge_memtest(void) {
    if (!g_system || !g_address_space) {
        RendererReport("memtest: bridge not started");
        return -1;
    }
    // GPU-visible memory has to live inside Core::DeviceMemory: the page table
    // stores (pointer - backing_base), so any other page would overflow it.
    static u8* page = nullptr;
    constexpr u64 kGpuAddress = 0x100000;
    constexpr u64 kBackingOffset = 256ULL << 20; // past the kernel reserve
    static bool mapped = false;
    try {
        if (!mapped) {
            page = g_system->DeviceMemory().buffer.BackingBasePointer() + kBackingOffset;
            auto& memory = g_system->ApplicationMemory();
            auto& gmmu = g_system->Host1x().memory_manager;
            const Core::Asid asid = gmmu.RegisterProcess(&memory);
            gmmu.Map(kGpuAddress, reinterpret_cast<VAddr>(page), 4096, asid);
            mapped = true;
        }
        page[0] = 0x5a;
        page[1] = 0xa5;
        const u8* translated = g_system->Host1x().memory_manager.GetPointer<u8>(kGpuAddress);
        const bool ok = translated && translated[0] == 0x5a && translated[1] == 0xa5;
        RendererReport("memtest: gpu=%#llx translated=%p ok=%d", (unsigned long long)kGpuAddress,
                       static_cast<const void*>(translated), ok ? 1 : 0);
        return ok ? 0 : -2;
    } catch (const std::exception& exception) {
        RendererReport("memtest: failed: %s", exception.what());
        return -3;
    }
}
// Draws a gradient into GPU-visible memory and hands it to Eden's present path.
// This is the "first frame" plumbing without guest commands: if the SurfaceView
// shows the gradient, Composite -> BlitScreen -> swapchain works end to end.
extern "C" int d3_gpu_bridge_composite_test(void) {
    if (!g_system) {
        RendererReport("composite: bridge not started");
        return -1;
    }
    constexpr u64 kGpuFramebuffer = 0x200000;
    constexpr u64 kBackingOffset = 512ULL << 20;
    constexpr u32 kWidth = 640;
    constexpr u32 kHeight = 360;
    constexpr u32 kStride = kWidth * 4;
    static bool mapped = false;
    try {
        u8* pixels = g_system->DeviceMemory().buffer.BackingBasePointer() + kBackingOffset;
        if (!mapped) {
            auto& memory = g_system->ApplicationMemory();
            auto& gmmu = g_system->Host1x().memory_manager;
            const Core::Asid asid = gmmu.RegisterProcess(&memory);
            gmmu.Map(kGpuFramebuffer, reinterpret_cast<VAddr>(pixels), kStride * kHeight, asid);
            mapped = true;
        }
        for (u32 y = 0; y < kHeight; ++y) {
            for (u32 x = 0; x < kWidth; ++x) {
                u8* pixel = pixels + y * kStride + x * 4;
                pixel[0] = static_cast<u8>(x * 255 / kWidth);        // R
                pixel[1] = static_cast<u8>(y * 255 / kHeight);       // G
                pixel[2] = static_cast<u8>((x ^ y) & 0xff);          // B
                pixel[3] = 0xff;                                     // A
            }
        }

        Tegra::FramebufferConfig framebuffer{};
        framebuffer.address = kGpuFramebuffer;
        framebuffer.width = kWidth;
        framebuffer.height = kHeight;
        framebuffer.stride = kStride;
        framebuffer.pixel_format = Service::android::PixelFormat::Rgba8888;
        framebuffer.transform_flags = Service::android::BufferTransformFlags::Unset;
        framebuffer.crop_rect = Common::Rectangle<int>{0, 0, static_cast<int>(kWidth),
                                                       static_cast<int>(kHeight)};
        framebuffer.blending = Tegra::BlendMode::Opaque;

        std::vector<Tegra::FramebufferConfig> layers;
        layers.push_back(framebuffer);
        g_system->GPU().RequestComposite(std::move(layers), {});
        const auto& layout = g_window->GetFramebufferLayout();
        RendererReport("composite: %ux%u framebuffer submitted (gpu=%#llx) layout=%ux%u", kWidth, kHeight,
                       (unsigned long long)kGpuFramebuffer, layout.width, layout.height);
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("composite: failed: %s", exception.what());
        return -2;
    }
}