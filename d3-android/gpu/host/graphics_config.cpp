#include "graphics_config.h"
#include "common/settings.h"
#include "video_core/vulkan_common/vulkan_library.h"
#include "core/frontend/emu_window.h"
#include <vulkan/vulkan.h>
#include <android/log.h>
#include <dlfcn.h>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <fstream>
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
std::string driver_status = "等待 Vulkan 初始化";
bool frozen;
bool native_widescreen;
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

extern "C" void d3_gpu_driver_status(char* output, size_t size) {
    std::lock_guard lock(config_mutex);
    std::snprintf(output, size, "%s", driver_status.c_str());
}

extern "C" int d3_gpu_configure(int scale, int widescreen, const char* libraries, const char* directory,
                                 const char* name) {
    std::lock_guard lock(config_mutex);
    if (frozen) return 1;
    if (scale != 10 && scale != 15) return -1;
    resolution = scale;
    native_widescreen = widescreen != 0;
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
    Settings::values.aspect_ratio.SetValue(native_widescreen ? Settings::AspectRatio::Stretch : Settings::AspectRatio::R16_9);
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
        access((driver_directory + driver_name).c_str(), R_OK) == 0) {
        void* handle = adrenotools_open_libvulkan(RTLD_NOW, 1, nullptr,
            native_directory.c_str(), driver_directory.c_str(), driver_name.c_str(), nullptr, nullptr);
        const char* loader_error = handle ? nullptr : dlerror();
        const std::string error = loader_error ? loader_error : "custom mapping/device validation failed";
        const bool has_device = handle && DriverHasDevice(handle);
        std::string custom_path = driver_directory + driver_name;
        std::string implementation_path = driver_directory + "libGLES_mali.so";
        char resolved[PATH_MAX];
        if (realpath(custom_path.c_str(), resolved)) custom_path = resolved;
        if (realpath(implementation_path.c_str(), resolved)) implementation_path = resolved;
        bool mapped = false;
        bool implementation_mapped = driver_name != "vulkan.mali.so";
        std::ifstream maps("/proc/self/maps");
        for (std::string line; std::getline(maps, line);) {
            if (line.find(custom_path) != std::string::npos) mapped = true;
            if (line.find(implementation_path) != std::string::npos) implementation_mapped = true;
        }
        if (has_device && mapped && implementation_mapped) {
            driver = std::make_shared<Common::DynamicLibrary>(handle);
            driver_status = "自定义库已映射并枚举到 GPU：" + driver_name;
            __android_log_print(ANDROID_LOG_INFO, "d3gpu", "custom Vulkan loader opened: %s", driver_name.c_str());
            return driver;
        }
        if (handle) dlclose(handle);
        __android_log_print(ANDROID_LOG_ERROR, "d3gpu", "custom driver load failed; using system Vulkan: mapped=%d core=%d device=%d error=%s",
                            mapped, implementation_mapped, has_device, error.c_str());
    }
    driver = std::make_shared<Common::DynamicLibrary>("libvulkan.so");
    driver_status = driver_name.empty() ? "系统 Vulkan" : "系统 Vulkan（自定义驱动未加载成功）";
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
