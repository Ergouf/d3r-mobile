#include "graphics_config.h"
#include "common/settings.h"
#include "video_core/vulkan_common/vulkan_library.h"
#include "core/frontend/emu_window.h"
#include <vulkan/vulkan.h>
#include <android/log.h>
#include <dlfcn.h>
#include <mutex>
#include <string>
#include <unistd.h>

extern "C" void* adrenotools_open_libvulkan(int, int, const char*, const char*,
                                           const char*, const char*, const char*, void**);
namespace {
std::mutex config_mutex;
int resolution = 10;
std::string native_directory, driver_directory, driver_name;
std::shared_ptr<Common::DynamicLibrary> driver;
bool frozen;
bool DriverHasDevice(void* handle) {
    auto get = reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(handle, "vkGetInstanceProcAddr"));
    if (!get) return false;
    auto create = reinterpret_cast<PFN_vkCreateInstance>(get(nullptr, "vkCreateInstance"));
    VkInstance instance{};
    VkInstanceCreateInfo info{.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    if (!create || create(&info, nullptr, &instance) != VK_SUCCESS) return false;
    auto enumerate = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(get(instance, "vkEnumeratePhysicalDevices"));
    auto destroy = reinterpret_cast<PFN_vkDestroyInstance>(get(instance, "vkDestroyInstance"));
    uint32_t count{};
    const bool valid = enumerate && enumerate(instance, &count, nullptr) == VK_SUCCESS && count;
    if (destroy) destroy(instance, nullptr);
    return valid;
}
}

extern "C" int d3_gpu_configure(int scale, const char* libraries, const char* directory,
                                 const char* name) {
    std::lock_guard lock(config_mutex);
    if (frozen || (scale != 10 && scale != 15)) return -1;
    resolution = scale;
    native_directory = libraries ? libraries : "";
    driver_directory = directory ? directory : "";
    if (!driver_directory.empty() && driver_directory.back() != '/') driver_directory += '/';
    driver_name = name ? name : "";
    return 0;
}

namespace D3 {
void ApplyGraphicsConfiguration() {
    std::lock_guard lock(config_mutex);
    frozen = true;
    const auto setup = resolution == 15 ? Settings::ResolutionSetup::Res3_2X
                                       : Settings::ResolutionSetup::Res1X;
    Settings::values.resolution_setup.SetValue(setup);
    Settings::TranslateResolutionInfo(setup, Settings::values.resolution_info);
    // Surface updates are serialized after WaitForComposite. Keep presentation
    // on that same thread so no queued presenter accesses an obsolete window.
    Settings::values.async_presentation.SetValue(false);
    __android_log_print(ANDROID_LOG_INFO, "d3gpu", "render scale=%.1fx (Eden render targets)",
                        Settings::values.resolution_info.up_factor);
}

std::shared_ptr<Common::DynamicLibrary> OpenDriverLibrary() {
    std::lock_guard lock(config_mutex);
    if (driver) return driver;
    if (!driver_name.empty() && driver_name.find('/') == std::string::npos &&
        driver_name.find('\\') == std::string::npos && !native_directory.empty() &&
        access((driver_directory + "/" + driver_name).c_str(), R_OK) == 0) {
        void* handle = adrenotools_open_libvulkan(RTLD_NOW, 1, nullptr,
            native_directory.c_str(), driver_directory.c_str(), driver_name.c_str(), nullptr, nullptr);
        if (handle && DriverHasDevice(handle)) {
            driver = std::make_shared<Common::DynamicLibrary>(handle);
            __android_log_print(ANDROID_LOG_INFO, "d3gpu", "custom Vulkan loader opened: %s", driver_name.c_str());
            return driver;
        }
        if (handle) dlclose(handle);
        __android_log_print(ANDROID_LOG_ERROR, "d3gpu", "custom driver load failed; using system Vulkan: %s", dlerror());
    }
    driver = std::make_shared<Common::DynamicLibrary>("libvulkan.so");
    __android_log_print(ANDROID_LOG_INFO, "d3gpu", "system Vulkan loader selected");
    return driver;
}
}

// Eden's upstream Android loader dispatch depends on a frontend architecture
// macro. Keep the host's loader explicit so headless probes and renderer agree.
namespace Vulkan {
std::shared_ptr<Common::DynamicLibrary> OpenLibrary(Core::Frontend::GraphicsContext* context) {
    return context ? context->GetDriverLibrary() : D3::OpenDriverLibrary();
}
}
