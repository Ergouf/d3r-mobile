// Vulkan bring-up probe.
//
// Creates an instance and a logical device through Eden's vulkan_common layer so
// a device log proves the driver, the code path and the static libc++ runtime
// all work inside libd3host.so.  Rendering (clear/present) is layered on top of
// the same objects in the next step.
#include <android/log.h>
#include <dlfcn.h>

#include <cstdarg>
#include <cstdio>
#include <exception>
#include <vector>

#include "common/dynamic_library.h"
#include "common/logging.h"
#include "core/frontend/emu_window.h"
#include "video_core/vulkan_common/vulkan_device.h"
#include "video_core/vulkan_common/vulkan_instance.h"
#include "video_core/vulkan_common/vulkan_library.h"
#include "video_core/vulkan_common/vulkan_surface.h"
#include "video_core/vulkan_common/vulkan_wrapper.h"

namespace {

void Report(const char* format, ...) {
    va_list args;
    va_start(args, format);
    __android_log_vprint(ANDROID_LOG_INFO, "d3gpu", format, args);
    va_end(args);
}

} // namespace

// Returns 0 on success, negative on failure; the exact value is logged.
extern "C" __attribute__((visibility("default"))) int d3_vk_probe(void* native_window) {
    try {
        auto library = Vulkan::OpenLibrary();
        if (!library) {
            Report("vk: libvulkan.so could not be loaded");
            return -1;
        }

        Vulkan::vk::InstanceDispatch dld;
        const auto instance = Vulkan::CreateInstance(*library, dld, VK_API_VERSION_1_2,
                                                     Core::Frontend::WindowSystemType::Android);
        const auto& dispatch = instance.Dispatch();

        u32 device_count = 0;
        if (dispatch.vkEnumeratePhysicalDevices(*instance, &device_count, nullptr) != VK_SUCCESS ||
            device_count == 0) {
            Report("vk: no physical devices");
            return -2;
        }
        std::vector<VkPhysicalDevice> devices(device_count);
        dispatch.vkEnumeratePhysicalDevices(*instance, &device_count, devices.data());

        // vkCreateAndroidSurfaceKHR dereferences the window, so a window-less
        // probe must stay headless instead of creating a null surface.
        VkSurfaceKHR raw_surface = VK_NULL_HANDLE;
        if (native_window) {
            Core::Frontend::EmuWindow::WindowSystemInfo window_info{};
            window_info.type = Core::Frontend::WindowSystemType::Android;
            window_info.render_surface = native_window;
            raw_surface = *Vulkan::CreateSurface(instance, window_info);
        }

        const Vulkan::vk::PhysicalDevice physical{devices[0], dispatch};
        Vulkan::Device device{*instance, physical, raw_surface, dispatch};

        Report("vk: driver=%s devices=%u surface=%p", device.GetDriverName().c_str(), device_count,
               static_cast<void*>(native_window));
        return 0;
    } catch (const std::exception& exception) {
        Report("vk: probe failed: %s", exception.what());
        return -3;
    } catch (...) {
        Report("vk: probe failed with an unknown error");
        return -4;
    }
}
