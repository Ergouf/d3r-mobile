#include <vulkan/vulkan.h>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <fstream>
#include <string>

extern "C" void* adrenotools_open_libvulkan(int, int, const char*, const char*, const char*, const char*, const char*, void**);

int main(int argument_count, char** arguments) {
    if (argument_count != 4 && (argument_count != 5 || std::strcmp(arguments[4], "--system-first"))) {
        std::fprintf(stderr, "usage: probe_driver HOOK_DIRECTORY DRIVER_DIRECTORY LIBRARY [--system-first]\n");
        return 2;
    }
    if (argument_count == 5) {
        void* system_loader = dlopen("libvulkan.so", RTLD_NOW);
        auto system_get = system_loader ? reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(system_loader, "vkGetInstanceProcAddr")) : nullptr;
        auto system_create = system_get ? reinterpret_cast<PFN_vkCreateInstance>(system_get(nullptr, "vkCreateInstance")) : nullptr;
        VkInstance system_instance{};
        VkInstanceCreateInfo system_info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
        if (!system_create || system_create(&system_info, nullptr, &system_instance) != VK_SUCCESS) return 7;
        auto system_destroy = reinterpret_cast<PFN_vkDestroyInstance>(system_get(system_instance, "vkDestroyInstance"));
        if (system_destroy) system_destroy(system_instance, nullptr);
        std::puts("system driver initialized before custom loader");
    }
    void* loader = adrenotools_open_libvulkan(RTLD_NOW, 1, nullptr, arguments[1], arguments[2], arguments[3], nullptr, nullptr);
    if (!loader) {
        const char* error = dlerror();
        std::fprintf(stderr, "loader failed: %s\n", error ? error : "unknown");
        return 3;
    }
    auto get = reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(loader, "vkGetInstanceProcAddr"));
    if (!get) return 4;
    auto create = reinterpret_cast<PFN_vkCreateInstance>(get(nullptr, "vkCreateInstance"));
    VkApplicationInfo application{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    application.pApplicationName = "D3 driver compatibility probe";
    application.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    info.pApplicationInfo = &application;
    VkInstance instance{};
    VkResult result = create ? create(&info, nullptr, &instance) : VK_ERROR_INITIALIZATION_FAILED;
    std::printf("vkCreateInstance=%d\n", result);
    if (result != VK_SUCCESS) return 5;
    auto enumerate = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(get(instance, "vkEnumeratePhysicalDevices"));
    auto properties = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(get(instance, "vkGetPhysicalDeviceProperties"));
    auto destroy = reinterpret_cast<PFN_vkDestroyInstance>(get(instance, "vkDestroyInstance"));
    uint32_t count = 1;
    VkPhysicalDevice device{};
    result = enumerate ? enumerate(instance, &count, &device) : VK_ERROR_INITIALIZATION_FAILED;
    std::printf("vkEnumeratePhysicalDevices=%d count=%u\n", result, count);
    if (result == VK_SUCCESS && count && properties) {
        VkPhysicalDeviceProperties details{};
        properties(device, &details);
        std::printf("device=%s vendor=%#x api=%#x driver=%#x\n", details.deviceName, details.vendorID, details.apiVersion, details.driverVersion);
        auto properties2 = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties2>(get(instance, "vkGetPhysicalDeviceProperties2"));
        if (properties2) {
            VkPhysicalDeviceDriverProperties driver_info{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
            VkPhysicalDeviceProperties2 chain{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
            chain.pNext = &driver_info;
            properties2(device, &chain);
            std::printf("driverName=%s driverInfo=%s\n", driver_info.driverName, driver_info.driverInfo);
        }
    }
    bool custom_mapped = false;
    bool core_mapped = std::strcmp(arguments[3], "vulkan.mali.so") != 0;
    std::ifstream maps("/proc/self/maps");
    const std::string expected = std::string(arguments[2]) + arguments[3];
    const std::string expected_core = std::string(arguments[2]) + "libGLES_mali.so";
    for (std::string line; std::getline(maps, line);) {
        if (line.find(expected) != std::string::npos) custom_mapped = true;
        if (line.find(expected_core) != std::string::npos) core_mapped = true;
        if (line.find("libGLES_mali.so") != std::string::npos || line.find(arguments[3]) != std::string::npos)
            std::printf("map=%s\n", line.c_str());
    }
    if (destroy) destroy(instance, nullptr);
    std::printf("custom_library_mapped=%d\n", custom_mapped);
    std::printf("custom_core_mapped=%d\n", core_mapped);
    return result == VK_SUCCESS && count && custom_mapped && core_mapped ? 0 : 6;
}
