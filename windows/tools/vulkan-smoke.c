#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>

static unsigned validation_errors;
static VKAPI_ATTR VkBool32 VKAPI_CALL debug_message(
    VkDebugUtilsMessageSeverityFlagBitsEXT severity, VkDebugUtilsMessageTypeFlagsEXT type,
    const VkDebugUtilsMessengerCallbackDataEXT *data, void *user) {
    (void)type;
    (void)user;
    if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT) ++validation_errors;
    fprintf(stderr, "validation: %s\n", data->pMessage);
    return VK_FALSE;
}

static int checked(VkResult value, const char *operation) {
    if (value == VK_SUCCESS) return 1;
    fprintf(stderr, "%s failed: %d\n", operation, value);
    return 0;
}
#define CHECK(call) do { if (!checked((call), #call)) goto done; } while (0)

static void json_string(const char *text) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') putchar('\\');
        if (*p < 32) printf("\\u%04x", *p); else putchar(*p);
    }
    putchar('"');
}

int main(int argc, char **argv) {
    int result = 1;
    uint32_t count = 0, loader = VK_API_VERSION_1_0;
    const char *layer = "VK_LAYER_KHRONOS_validation";
    const char *extension = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
    VkInstance instance = VK_NULL_HANDLE;
    VkDebugUtilsMessengerEXT messenger = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkShaderModule shader = VK_NULL_HANDLE;
    VkPhysicalDevice *physical = NULL;
    VkLayerProperties *layers = NULL;
    VkQueueFamilyProperties *queues = NULL;
    uint32_t *code = NULL;
    FILE *file = NULL;
    VkPhysicalDeviceProperties selected = {0};
    VkDebugUtilsMessengerCreateInfoEXT debug = {
        .sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT,
        .messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT |
                           VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT,
        .messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT |
                       VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT |
                       VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT,
        .pfnUserCallback = debug_message
    };
    VkApplicationInfo application = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "Diablo Windows dependency smoke test",
        .apiVersion = VK_API_VERSION_1_3
    };
    VkInstanceCreateInfo create = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pNext = &debug, .pApplicationInfo = &application,
        .enabledLayerCount = 1, .ppEnabledLayerNames = &layer,
        .enabledExtensionCount = 1, .ppEnabledExtensionNames = &extension
    };
    CHECK(vkEnumerateInstanceVersion(&loader));
    CHECK(vkEnumerateInstanceLayerProperties(&count, NULL));
    layers = calloc(count, sizeof *layers);
    if (!layers) goto done;
    CHECK(vkEnumerateInstanceLayerProperties(&count, layers));
    int found = 0;
    for (uint32_t i = 0; i < count; ++i) found |= strcmp(layers[i].layerName, layer) == 0;
    if (!found) { fprintf(stderr, "Khronos validation layer was not found\n"); goto done; }
    CHECK(vkCreateInstance(&create, NULL, &instance));
    PFN_vkCreateDebugUtilsMessengerEXT make_debug = (PFN_vkCreateDebugUtilsMessengerEXT)
        vkGetInstanceProcAddr(instance, "vkCreateDebugUtilsMessengerEXT");
    if (!make_debug) goto done;
    CHECK(make_debug(instance, &debug, NULL, &messenger));
    CHECK(vkEnumeratePhysicalDevices(instance, &count, NULL));
    physical = calloc(count, sizeof *physical);
    if (!physical) goto done;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, physical));
    VkPhysicalDevice intel = VK_NULL_HANDLE;
    for (uint32_t i = 0; i < count; ++i) {
        VkPhysicalDeviceProperties properties;
        vkGetPhysicalDeviceProperties(physical[i], &properties);
        if (properties.vendorID == 0x8086 && properties.apiVersion >= VK_API_VERSION_1_3) {
            selected = properties;
            intel = physical[i];
            break;
        }
    }
    if (!intel) { fprintf(stderr, "No Intel Vulkan 1.3 device found\n"); goto done; }
    uint32_t queue_count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(intel, &queue_count, NULL);
    queues = calloc(queue_count, sizeof *queues);
    if (!queues) goto done;
    vkGetPhysicalDeviceQueueFamilyProperties(intel, &queue_count, queues);
    uint32_t family = 0;
    while (family < queue_count && !(queues[family].queueFlags & VK_QUEUE_GRAPHICS_BIT)) ++family;
    if (family == queue_count) goto done;
    float priority = 1.0f;
    VkDeviceQueueCreateInfo queue_create = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority
    };
    VkDeviceCreateInfo device_create = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue_create
    };
    CHECK(vkCreateDevice(intel, &device_create, NULL, &device));
    if (argc != 2 || !(file = fopen(argv[1], "rb"))) goto done;
    if (fseek(file, 0, SEEK_END) != 0) goto done;
    long bytes = ftell(file);
    if (bytes <= 0 || bytes % 4 || fseek(file, 0, SEEK_SET) != 0) goto done;
    code = malloc((size_t)bytes);
    if (!code || fread(code, 1, (size_t)bytes, file) != (size_t)bytes) goto done;
    fclose(file); file = NULL;
    VkShaderModuleCreateInfo shader_create = {
        .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = (size_t)bytes, .pCode = code
    };
    CHECK(vkCreateShaderModule(device, &shader_create, NULL, &shader));
    CHECK(vkDeviceWaitIdle(device));
    result = 0;
done:
    if (file) fclose(file);
    if (shader) vkDestroyShaderModule(device, shader, NULL);
    if (device) vkDestroyDevice(device, NULL);
    if (messenger) {
        PFN_vkDestroyDebugUtilsMessengerEXT destroy_debug = (PFN_vkDestroyDebugUtilsMessengerEXT)
            vkGetInstanceProcAddr(instance, "vkDestroyDebugUtilsMessengerEXT");
        if (destroy_debug) destroy_debug(instance, messenger, NULL);
    }
    if (instance) vkDestroyInstance(instance, NULL);
    free(code); free(queues); free(physical); free(layers);
    if (validation_errors) result = 1;
    if (result == 0) {
        printf("{\"validation_layer\":true,\"validation_errors\":%u,\"device_created\":true,\"shader_module_created\":true,\"loader_api\":\"%u.%u.%u\",\"device_name\":",
               validation_errors, VK_API_VERSION_MAJOR(loader), VK_API_VERSION_MINOR(loader), VK_API_VERSION_PATCH(loader));
        json_string(selected.deviceName);
        printf(",\"vendor_id\":%u,\"device_api\":\"%u.%u.%u\",\"driver_version_raw\":%u}\n",
               selected.vendorID, VK_API_VERSION_MAJOR(selected.apiVersion), VK_API_VERSION_MINOR(selected.apiVersion),
               VK_API_VERSION_PATCH(selected.apiVersion), selected.driverVersion);
    }
    return result;
}
