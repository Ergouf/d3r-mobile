/* Native Win32/Vulkan clear-and-present probe. No game data, input injection or display-mode changes.
   clang -std=c11 -O2 -Wall -Wextra -Werror vulkan-present-probe.c -o vulkan-present-probe.exe -lvulkan-1 -luser32
   vulkan-present-probe.exe --seconds=30 --output=probe.csv [--immediate] [--width=1280 --height=720]
   vulkan-present-probe.exe --check-exclusive (FSE capabilities/formats query only; no swapchain or rendering)
   vulkan-present-probe.exe --exclusive [--topmost] (application-controlled exclusive access; current primary mode only)
   CSV rows measure host calls; drops count failed API attempts, NOT ETW-confirmed unshown frames. */
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_USE_PLATFORM_WIN32_KHR
#include <windows.h>
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif
#define SLOTS 2

typedef struct { double sum, max; uint64_t over20; } Metric;
typedef struct { VkFence fence; VkSemaphore acquired; VkCommandBuffer command; } Frame;
static LARGE_INTEGER frequency;
static int closing;
static int64_t tick(void) { LARGE_INTEGER q; QueryPerformanceCounter(&q); return q.QuadPart; }
static double ms(int64_t ticks) { return (double)ticks * 1000.0 / (double)frequency.QuadPart; }
static void add(Metric *m, double value) { m->sum += value; if (value > m->max) m->max = value; m->over20 += value > 20.0; }
static void metric(const char *name, const Metric *m) {
    printf(" %s_sum_ms=%.3f %s_max_ms=%.3f %s_gt20=%llu", name, m->sum, name, m->max, name, (unsigned long long)m->over20);
}
static void summary(uint64_t frames, uint64_t attempts, uint64_t drops, uint64_t deadline_skips,
                    double elapsed, const Metric *fence, const Metric *acquire, const Metric *submit,
                    const Metric *present, const Metric *sleep) {
    printf("frames=%llu attempts=%llu api_drops=%llu deadline_skips=%llu elapsed_s=%.3f host_present_fps=%.3f",
           (unsigned long long)frames, (unsigned long long)attempts, (unsigned long long)drops,
           (unsigned long long)deadline_skips, elapsed, elapsed > 0 ? frames / elapsed : 0);
    metric("fence", fence); metric("acquire", acquire); metric("submit", submit); metric("present", present); metric("limiter_wait", sleep);
    putchar('\n'); fflush(stdout);
}
static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_CLOSE) { closing = 1; DestroyWindow(window); return 0; }
    if (message == WM_DESTROY) { closing = 1; PostQuitMessage(0); return 0; }
    if (message == WM_PAINT) { ValidateRect(window, NULL); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}
static const char *arg_value(int *i, int argc, char **argv, const char *name) {
    size_t n = strlen(name);
    if (!strncmp(argv[*i], name, n) && argv[*i][n] == '=') return argv[*i] + n + 1;
    if (!strcmp(argv[*i], name) && *i + 1 < argc) return argv[++*i];
    return NULL;
}
static int success(VkResult result, const char *call) {
    if (result == VK_SUCCESS) return 1;
    fprintf(stderr, "%s returned VkResult=%d\n", call, result); return 0;
}
/* Physical-device extension queries do not require creating or enabling a logical device. */
static VkResult has_extension(VkPhysicalDevice gpu, const char *name, int *available) {
    uint32_t count = 0;
    *available = 0;
    VkResult r = gpu ? vkEnumerateDeviceExtensionProperties(gpu, NULL, &count, NULL)
                     : vkEnumerateInstanceExtensionProperties(NULL, &count, NULL);
    if (r != VK_SUCCESS || !count) return r;
    VkExtensionProperties *extensions = calloc(count, sizeof *extensions);
    if (!extensions) return VK_ERROR_OUT_OF_HOST_MEMORY;
    r = gpu ? vkEnumerateDeviceExtensionProperties(gpu, NULL, &count, extensions)
            : vkEnumerateInstanceExtensionProperties(NULL, &count, extensions);
    if (r == VK_SUCCESS) for (uint32_t i = 0; i < count; ++i)
        if (!strcmp(extensions[i].extensionName, name)) { *available = 1; break; }
    free(extensions);
    return r;
}
static VkResult query_exclusive_formats(VkInstance instance, VkPhysicalDevice gpu,
                                        const VkPhysicalDeviceSurfaceInfo2KHR *info,
                                        VkSurfaceFormatKHR **formats, uint32_t *format_count) {
    PFN_vkGetPhysicalDeviceSurfaceFormats2KHR query = (PFN_vkGetPhysicalDeviceSurfaceFormats2KHR)
        vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceSurfaceFormats2KHR");
    if (!query) { fputs("Exclusive Formats2 query unavailable\n", stderr); return VK_ERROR_EXTENSION_NOT_PRESENT; }
    uint32_t count = 0;
    VkResult r = query(gpu, info, &count, NULL);
    if (r != VK_SUCCESS) return r;
    if (!count) { fputs("Exclusive Formats2 returned no formats\n", stderr); return VK_ERROR_FORMAT_NOT_SUPPORTED; }
    VkSurfaceFormat2KHR *queried = calloc(count, sizeof *queried);
    VkSurfaceFormatKHR *result = calloc(count, sizeof *result);
    if (!queried || !result) { free(result); free(queried); return VK_ERROR_OUT_OF_HOST_MEMORY; }
    for (uint32_t i = 0; i < count; ++i) queried[i].sType = VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR;
    r = query(gpu, info, &count, queried);
    if (r == VK_SUCCESS && count) {
        printf("exclusive-formats: query=Formats2 policy=APPLICATION_CONTROLLED hmonitor_chain=1 count=%u\n", count);
        for (uint32_t i = 0; i < count; ++i) {
            result[i] = queried[i].surfaceFormat;
            printf("exclusive-format: index=%u format=%d color_space=%d preferred_bgra8_srgb=%d\n", i,
                result[i].format, result[i].colorSpace,
                result[i].format == VK_FORMAT_B8G8R8A8_UNORM && result[i].colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR);
        }
        *formats = result; *format_count = count;
    } else { free(result); if (r == VK_SUCCESS) r = VK_ERROR_FORMAT_NOT_SUPPORTED; }
    free(queried);
    return r;
}
static int check_exclusive_surface(VkInstance instance, VkPhysicalDevice gpu, VkSurfaceKHR surface, HWND window,
                                   VkSurfaceCapabilitiesKHR *surface_caps, int *supported,
                                   VkSurfaceFormatKHR **formats, uint32_t *format_count) {
    *supported = 0;
    int available = 0;
    VkResult r = has_extension(gpu, VK_EXT_FULL_SCREEN_EXCLUSIVE_EXTENSION_NAME, &available);
    if (!success(r, "enumerate full-screen exclusive device extension")) return 1;
    if (!available) {
        puts("exclusive-check: status=unsupported reason=device_extension_missing device_fse=0 fullScreenExclusiveSupported=unavailable");
        return 3;
    }
    PFN_vkGetPhysicalDeviceSurfaceCapabilities2KHR query = (PFN_vkGetPhysicalDeviceSurfaceCapabilities2KHR)
        vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceSurfaceCapabilities2KHR");
    if (!query) {
        puts("exclusive-check: status=error reason=surface_capabilities2_entry_missing fullScreenExclusiveSupported=unavailable");
        return 1;
    }
    HMONITOR monitor = MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST);
    if (!monitor) { fprintf(stderr, "MonitorFromWindow error=%lu\n", GetLastError()); return 1; }
    VkSurfaceFullScreenExclusiveWin32InfoEXT win32 = {
        .sType = VK_STRUCTURE_TYPE_SURFACE_FULL_SCREEN_EXCLUSIVE_WIN32_INFO_EXT, .hmonitor = monitor};
    VkSurfaceFullScreenExclusiveInfoEXT policy = {
        .sType = VK_STRUCTURE_TYPE_SURFACE_FULL_SCREEN_EXCLUSIVE_INFO_EXT, .pNext = &win32,
        .fullScreenExclusive = VK_FULL_SCREEN_EXCLUSIVE_APPLICATION_CONTROLLED_EXT};
    VkPhysicalDeviceSurfaceInfo2KHR info = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SURFACE_INFO_2_KHR, .pNext = &policy, .surface = surface};
    VkSurfaceCapabilitiesFullScreenExclusiveEXT exclusive = {
        .sType = VK_STRUCTURE_TYPE_SURFACE_CAPABILITIES_FULL_SCREEN_EXCLUSIVE_EXT};
    VkSurfaceCapabilities2KHR caps = {.sType = VK_STRUCTURE_TYPE_SURFACE_CAPABILITIES_2_KHR, .pNext = &exclusive};
    r = query(gpu, &info, &caps);
    printf("exclusive-check: instance_caps2=1 device_fse=1 hwnd=%p hmonitor=%p policy=APPLICATION_CONTROLLED result=%d ",
        (void *)window, (void *)monitor, r);
    if (r == VK_SUCCESS)
        printf("fullScreenExclusiveSupported=%u status=%s\n", exclusive.fullScreenExclusiveSupported,
            exclusive.fullScreenExclusiveSupported ? "supported" : "unsupported_surface");
    else puts("fullScreenExclusiveSupported=unavailable status=query_failed");
    if (r == VK_SUCCESS) {
        *supported = exclusive.fullScreenExclusiveSupported != VK_FALSE;
        if (surface_caps) *surface_caps = caps.surfaceCapabilities;
        /* Reuse the exact policy/monitor input used for capabilities, not a legacy no-chain format query. */
        r = query_exclusive_formats(instance, gpu, &info, formats, format_count);
        if (!success(r, "query full-screen exclusive surface formats")) return 1;
    }
    return r == VK_SUCCESS ? 0 : 1;
}
#define TRY(call) do { if (!success((call), #call)) goto cleanup; } while (0)

int main(int argc, char **argv) {
    int result = 1, immediate = 0, width = 0, height = 0, high_resolution_timer = 1, check_exclusive = 0;
    int exclusive = 0, exclusive_acquired = 0, wait_for_focus = 0, topmost = 0;
    double seconds = 30.0;
    unsigned target_fps = 60;
    const char *output = NULL;
    FILE *csv = NULL;
    HWND window = NULL;
    HINSTANCE module = GetModuleHandleW(NULL);
    HANDLE timer = NULL;
    VkInstance instance = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    PFN_vkAcquireFullScreenExclusiveModeEXT acquire_exclusive = NULL;
    PFN_vkReleaseFullScreenExclusiveModeEXT release_exclusive = NULL;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkImage *images = NULL;
    VkSemaphore *ready = NULL;
    uint32_t image_count = 0;
    VkPhysicalDevice *physical = NULL;
    VkSurfaceFormatKHR *formats = NULL;
    uint32_t format_count = 0;
    VkPresentModeKHR *present_modes = NULL;
    Frame frame[SLOTS] = {{0}};
    Metric fence_metric = {0}, acquire_metric = {0}, submit_metric = {0}, present_metric = {0}, sleep_metric = {0};
    uint64_t frames = 0, attempts = 0, drops = 0, deadline_skips = 0;
    int64_t epoch = 0;
    for (int i = 1; i < argc; ++i) {
        const char *v;
        if (!strcmp(argv[i], "--immediate")) immediate = 1;
        else if (!strcmp(argv[i], "--check-exclusive")) check_exclusive = 1;
        else if (!strcmp(argv[i], "--exclusive")) exclusive = 1;
        else if (!strcmp(argv[i], "--topmost")) topmost = 1;
        else if (!strcmp(argv[i], "--wait-for-focus")) wait_for_focus = 1;
        else if ((v = arg_value(&i, argc, argv, "--seconds"))) seconds = strtod(v, NULL);
        else if ((v = arg_value(&i, argc, argv, "--fps"))) target_fps = (unsigned)strtoul(v, NULL, 10);
        else if ((v = arg_value(&i, argc, argv, "--width"))) width = atoi(v);
        else if ((v = arg_value(&i, argc, argv, "--height"))) height = atoi(v);
        else if ((v = arg_value(&i, argc, argv, "--output"))) output = v;
        else { fprintf(stderr, "Unknown/incomplete argument: %s\n", argv[i]); return 2; }
    }
    if (!(seconds > 0 && seconds <= 3600) || width < 0 || height < 0 || target_fps < 10 || target_fps > 240) { fputs("Invalid duration, rate or size\n", stderr); return 2; }
    if (check_exclusive && exclusive) { fputs("--check-exclusive cannot be combined with --exclusive\n", stderr); return 2; }
    if (topmost && !exclusive) { fputs("--topmost requires --exclusive\n", stderr); return 2; }
    if (check_exclusive && wait_for_focus) { fputs("--check-exclusive cannot be combined with --wait-for-focus\n", stderr); return 2; }
    if (check_exclusive && output) { fputs("--check-exclusive does not produce a frame CSV; omit --output\n", stderr); return 2; }
    QueryPerformanceFrequency(&frequency);
    SetProcessDPIAware();
    if (!width) width = GetSystemMetrics(SM_CXSCREEN);
    if (!height) height = GetSystemMetrics(SM_CYSCREEN);
    if (exclusive && (width != GetSystemMetrics(SM_CXSCREEN) || height != GetSystemMetrics(SM_CYSCREEN))) {
        fputs("--exclusive requires the current full primary-screen dimensions; no display mode will be changed\n", stderr);
        return 2;
    }
    if (output) {
        csv = fopen(output, "wb");
        if (!csv) { perror(output); goto cleanup; }
        setvbuf(csv, NULL, _IOFBF, 1 << 20);
        fputs("frame,slot,image,scheduled_qpc,limiter_begin_qpc,frame_start_qpc,submit_qpc,frame_end_qpc,qpc_frequency,limiter_wait_ms,start_late_ms,fence_wait_ms,acquire_ms,submit_ms,present_ms,cpu_frame_ms,fence_result,acquire_result,submit_result,present_result,deadline_skips_total\n", csv);
    }
    WNDCLASSW wc = {0};
    wc.lpfnWndProc = window_proc; wc.hInstance = module; wc.lpszClassName = L"DiabloVulkanPresentProbe";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    if (!RegisterClassW(&wc)) { fprintf(stderr, "RegisterClass error=%lu\n", GetLastError()); goto cleanup; }
    wchar_t title[128];
    swprintf(title, sizeof title / sizeof title[0], L"Vulkan Present Probe - %u FPS %ls clear", target_fps,
        check_exclusive ? L"capability check" : exclusive ? L"exclusive" : L"windowed");
    window = CreateWindowExW(topmost ? WS_EX_TOPMOST : 0, wc.lpszClassName, title, WS_POPUP,
                             0, 0, width, height, NULL, NULL, module, NULL);
    if (!window) { fprintf(stderr, "CreateWindow error=%lu\n", GetLastError()); goto cleanup; }
    ShowWindow(window, SW_SHOW); UpdateWindow(window);
    const char *instance_extensions[] = {VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_WIN32_SURFACE_EXTENSION_NAME,
        VK_KHR_GET_SURFACE_CAPABILITIES_2_EXTENSION_NAME};
    if (check_exclusive || exclusive) {
        int available = 0;
        TRY(has_extension(VK_NULL_HANDLE, VK_KHR_GET_SURFACE_CAPABILITIES_2_EXTENSION_NAME, &available));
        if (!available) {
            puts("exclusive-check: status=unsupported reason=instance_extension_missing instance_caps2=0 fullScreenExclusiveSupported=unavailable");
            result = 3; goto cleanup;
        }
    }
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "Native clear/present probe", .apiVersion = VK_API_VERSION_1_3};
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app,
        .enabledExtensionCount = check_exclusive || exclusive ? 3u : 2u, .ppEnabledExtensionNames = instance_extensions};
    TRY(vkCreateInstance(&ici, NULL, &instance));
    VkWin32SurfaceCreateInfoKHR sci = {.sType = VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR, .hinstance = module, .hwnd = window};
    TRY(vkCreateWin32SurfaceKHR(instance, &sci, NULL, &surface));
    uint32_t count = 0, family = UINT32_MAX;
    VkPhysicalDevice gpu = VK_NULL_HANDLE;
    TRY(vkEnumeratePhysicalDevices(instance, &count, NULL));
    physical = calloc(count, sizeof *physical); if (!physical) goto cleanup;
    TRY(vkEnumeratePhysicalDevices(instance, &count, physical));
    VkPhysicalDeviceProperties properties = {0};
    for (int pass = 0; pass < 2 && !gpu; ++pass) for (uint32_t i = 0; i < count && !gpu; ++i) {
        VkPhysicalDeviceProperties p; vkGetPhysicalDeviceProperties(physical[i], &p);
        if (p.apiVersion < VK_API_VERSION_1_3 || (pass == 0 && p.vendorID != 0x8086)) continue;
        uint32_t nq = 0; vkGetPhysicalDeviceQueueFamilyProperties(physical[i], &nq, NULL);
        VkQueueFamilyProperties *queues = calloc(nq, sizeof *queues); if (!queues) goto cleanup;
        vkGetPhysicalDeviceQueueFamilyProperties(physical[i], &nq, queues);
        for (uint32_t q = 0; q < nq; ++q) {
            VkBool32 supported = 0;
            VkResult support = vkGetPhysicalDeviceSurfaceSupportKHR(physical[i], q, surface, &supported);
            if (support == VK_SUCCESS && supported && (queues[q].queueFlags & VK_QUEUE_GRAPHICS_BIT)) { gpu = physical[i]; family = q; properties = p; break; }
        }
        free(queues);
    }
    if (!gpu) { fputs("No Vulkan 1.3 graphics/present device\n", stderr); goto cleanup; }
    VkSurfaceCapabilitiesKHR capabilities;
    if (check_exclusive || exclusive) {
        int supported = 0;
        printf("exclusive-check: gpu=%s driver_raw=%u window=%dx%d\n", properties.deviceName, properties.driverVersion, width, height);
        result = check_exclusive_surface(instance, gpu, surface, window, &capabilities, &supported, &formats, &format_count);
        if (check_exclusive) {
            puts("exclusive-check: logical_device_created=0 swapchain_created=0 mode_acquired=0 rendered_frames=0");
            goto cleanup;
        }
        if (result != 0 || !supported) {
            if (result == 0) result = 3;
            fputs("Exclusive surface support unavailable; refusing windowed fallback\n", stderr);
            goto cleanup;
        }
        result = 1; /* success is set only once exclusive acquisition and setup finish */
    }
    VkSurfaceFullScreenExclusiveWin32InfoEXT exclusive_win32 = {
        .sType = VK_STRUCTURE_TYPE_SURFACE_FULL_SCREEN_EXCLUSIVE_WIN32_INFO_EXT,
        .hmonitor = exclusive ? MonitorFromWindow(window, MONITOR_DEFAULTTONULL) : NULL};
    VkSurfaceFullScreenExclusiveInfoEXT exclusive_policy = {
        .sType = VK_STRUCTURE_TYPE_SURFACE_FULL_SCREEN_EXCLUSIVE_INFO_EXT, .pNext = &exclusive_win32,
        .fullScreenExclusive = VK_FULL_SCREEN_EXCLUSIVE_APPLICATION_CONTROLLED_EXT};
    VkPhysicalDeviceSurfaceInfo2KHR exclusive_info = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SURFACE_INFO_2_KHR, .pNext = &exclusive_policy, .surface = surface};
    if (exclusive) {
        MONITORINFO monitor_info = {.cbSize = sizeof monitor_info};
        RECT window_rect;
        if (!exclusive_win32.hmonitor || !GetMonitorInfoW(exclusive_win32.hmonitor, &monitor_info) ||
            !GetWindowRect(window, &window_rect) || !(monitor_info.dwFlags & MONITORINFOF_PRIMARY) ||
            !EqualRect(&window_rect, &monitor_info.rcMonitor)) {
            fputs("Exclusive window does not exactly cover the primary monitor; refusing mode change\n", stderr);
            goto cleanup;
        }
    }
    float priority = 1;
    VkDeviceQueueCreateInfo qci = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
    const char *device_extensions[] = {VK_KHR_SWAPCHAIN_EXTENSION_NAME, VK_EXT_FULL_SCREEN_EXCLUSIVE_EXTENSION_NAME};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci,
        .enabledExtensionCount = exclusive ? 2u : 1u, .ppEnabledExtensionNames = device_extensions};
    TRY(vkCreateDevice(gpu, &dci, NULL, &device));
    VkQueue queue; vkGetDeviceQueue(device, family, 0, &queue);
    if (!exclusive) TRY(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(gpu, surface, &capabilities));
    if (exclusive) {
        acquire_exclusive = (PFN_vkAcquireFullScreenExclusiveModeEXT)vkGetDeviceProcAddr(device, "vkAcquireFullScreenExclusiveModeEXT");
        release_exclusive = (PFN_vkReleaseFullScreenExclusiveModeEXT)vkGetDeviceProcAddr(device, "vkReleaseFullScreenExclusiveModeEXT");
        if (!acquire_exclusive || !release_exclusive) { fputs("Exclusive device entry points unavailable\n", stderr); goto cleanup; }
    }
    if (!(capabilities.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT)) { fputs("Swapchain transfer-dst unsupported\n", stderr); goto cleanup; }
    if (!exclusive) {
        TRY(vkGetPhysicalDeviceSurfaceFormatsKHR(gpu, surface, &count, NULL));
        if (!count) goto cleanup;
        formats = calloc(count, sizeof *formats); if (!formats) goto cleanup;
        TRY(vkGetPhysicalDeviceSurfaceFormatsKHR(gpu, surface, &count, formats));
        format_count = count;
    }
    VkSurfaceFormatKHR format = formats[0];
    for (uint32_t i = 0; i < format_count; ++i) if (formats[i].format == VK_FORMAT_B8G8R8A8_UNORM && formats[i].colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) { format = formats[i]; break; }
    if (format.format == VK_FORMAT_UNDEFINED) format.format = VK_FORMAT_B8G8R8A8_UNORM;
    if (exclusive) printf("exclusive-selected-format: query=Formats2 format=%d color_space=%d topmost=%d\n", format.format, format.colorSpace, topmost);
    PFN_vkGetPhysicalDeviceSurfacePresentModes2EXT exclusive_modes = NULL;
    if (exclusive) {
        exclusive_modes = (PFN_vkGetPhysicalDeviceSurfacePresentModes2EXT)vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceSurfacePresentModes2EXT");
        if (!exclusive_modes) { fputs("Exclusive present-mode query unavailable\n", stderr); goto cleanup; }
        TRY(exclusive_modes(gpu, &exclusive_info, &count, NULL));
    } else TRY(vkGetPhysicalDeviceSurfacePresentModesKHR(gpu, surface, &count, NULL));
    present_modes = calloc(count, sizeof *present_modes); if (!present_modes) goto cleanup;
    if (exclusive) TRY(exclusive_modes(gpu, &exclusive_info, &count, present_modes));
    else TRY(vkGetPhysicalDeviceSurfacePresentModesKHR(gpu, surface, &count, present_modes));
    VkPresentModeKHR mode = VK_PRESENT_MODE_FIFO_KHR;
    if (immediate) {
        int available = 0;
        for (uint32_t i = 0; i < count; ++i) available |= present_modes[i] == VK_PRESENT_MODE_IMMEDIATE_KHR;
        if (!available) { fputs("IMMEDIATE unsupported; refusing silent mode fallback\n", stderr); goto cleanup; }
        mode = VK_PRESENT_MODE_IMMEDIATE_KHR;
    }
    VkExtent2D extent = capabilities.currentExtent;
    if (extent.width == UINT32_MAX) {
        extent = (VkExtent2D){(uint32_t)width, (uint32_t)height};
        if (extent.width < capabilities.minImageExtent.width) extent.width = capabilities.minImageExtent.width;
        if (extent.width > capabilities.maxImageExtent.width) extent.width = capabilities.maxImageExtent.width;
        if (extent.height < capabilities.minImageExtent.height) extent.height = capabilities.minImageExtent.height;
        if (extent.height > capabilities.maxImageExtent.height) extent.height = capabilities.maxImageExtent.height;
    }
    uint32_t requested_images = capabilities.minImageCount > 3 ? capabilities.minImageCount : 3;
    if (capabilities.maxImageCount && requested_images > capabilities.maxImageCount) requested_images = capabilities.maxImageCount;
    VkCompositeAlphaFlagBitsKHR alpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    if (!(capabilities.supportedCompositeAlpha & alpha)) alpha = (VkCompositeAlphaFlagBitsKHR)(capabilities.supportedCompositeAlpha & (0u - capabilities.supportedCompositeAlpha));
    if (exclusive && (extent.width != (uint32_t)width || extent.height != (uint32_t)height)) {
        fputs("Exclusive surface extent differs from current primary-screen size; refusing mode change\n", stderr); goto cleanup;
    }
    VkSwapchainCreateInfoKHR swap = {.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
        .pNext = exclusive ? &exclusive_policy : NULL, .surface = surface,
        .minImageCount = requested_images, .imageFormat = format.format, .imageColorSpace = format.colorSpace, .imageExtent = extent,
        .imageArrayLayers = 1, .imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT, .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .preTransform = capabilities.currentTransform, .compositeAlpha = alpha, .presentMode = mode, .clipped = VK_TRUE};
    TRY(vkCreateSwapchainKHR(device, &swap, NULL, &swapchain));
    if (exclusive || wait_for_focus) {
        /* The caller can activate this window with their normal UI automation. The probe only observes
           foreground ownership: do not steal focus, inject input, or retry an exclusive acquisition. */
        printf("probe-await-focus: hwnd=%p timeout_ms=30000\n", (void *)window); fflush(stdout);
        int64_t focus_start = tick();
        while (!closing && GetForegroundWindow() != window && ms(tick() - focus_start) < 30000.0) {
            MSG message;
            while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
                if (message.message == WM_QUIT) closing = 1;
                TranslateMessage(&message); DispatchMessageW(&message);
            }
            if (!closing && GetForegroundWindow() != window) Sleep(10);
        }
        if (closing || GetForegroundWindow() != window) {
            fprintf(stderr, "probe-focus: status=%s foreground=%p expected=%p fallback=disabled\n",
                closing ? "window_closed" : "timeout", (void *)GetForegroundWindow(), (void *)window);
            goto cleanup;
        }
        printf("probe-focus: status=foreground wait_ms=%.3f\n", ms(tick() - focus_start)); fflush(stdout);
    }
    if (exclusive) {
        VkResult acquired = acquire_exclusive(device, swapchain);
        printf("exclusive-acquire: result=%d fallback=disabled\n", acquired); fflush(stdout);
        if (!success(acquired, "vkAcquireFullScreenExclusiveModeEXT")) goto cleanup;
        exclusive_acquired = 1;
    }
    TRY(vkGetSwapchainImagesKHR(device, swapchain, &image_count, NULL));
    images = calloc(image_count, sizeof *images); ready = calloc(image_count, sizeof *ready);
    if (!images || !ready) goto cleanup;
    TRY(vkGetSwapchainImagesKHR(device, swapchain, &image_count, images));
    VkSemaphoreCreateInfo sem = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    for (uint32_t i = 0; i < image_count; ++i) TRY(vkCreateSemaphore(device, &sem, NULL, &ready[i]));
    VkCommandPoolCreateInfo pci = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = family};
    TRY(vkCreateCommandPool(device, &pci, NULL, &pool));
    for (uint32_t i = 0; i < SLOTS; ++i) {
        VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, .flags = VK_FENCE_CREATE_SIGNALED_BIT};
        TRY(vkCreateFence(device, &fci, NULL, &frame[i].fence));
        TRY(vkCreateSemaphore(device, &sem, NULL, &frame[i].acquired));
        VkCommandBufferAllocateInfo cai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
        TRY(vkAllocateCommandBuffers(device, &cai, &frame[i].command));
    }
    timer = CreateWaitableTimerExW(NULL, NULL, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    if (!timer) { high_resolution_timer = 0; timer = CreateWaitableTimerExW(NULL, NULL, 0, TIMER_ALL_ACCESS); }
    if (!timer) { fprintf(stderr, "CreateWaitableTimer error=%lu\n", GetLastError()); goto cleanup; }
    printf("gpu=%s driver_raw=%u api=%u.%u.%u extent=%ux%u requested_images=%u images=%u mode=%s frame_slots=%d high_resolution_timer=%d qpc_frequency=%lld seconds=%.3f target_fps=%u exclusive_acquired=%d\n",
        properties.deviceName, properties.driverVersion, VK_API_VERSION_MAJOR(properties.apiVersion), VK_API_VERSION_MINOR(properties.apiVersion), VK_API_VERSION_PATCH(properties.apiVersion),
        extent.width, extent.height, requested_images, image_count, immediate ? "IMMEDIATE" : "FIFO", SLOTS, high_resolution_timer, (long long)frequency.QuadPart, seconds, target_fps, exclusive_acquired);
    fflush(stdout);
    epoch = tick(); uint64_t schedule_tick = 0;
    result = 0;
    while (!closing) {
        MSG message;
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) { if (message.message == WM_QUIT) closing = 1; TranslateMessage(&message); DispatchMessageW(&message); }
        if (closing || ms(tick() - epoch) >= seconds * 1000.0) break;
        int64_t scheduled = epoch + (int64_t)(schedule_tick * (uint64_t)frequency.QuadPart / target_fps);
        int64_t sleep_begin = tick();
        if (scheduled > sleep_begin) {
            LARGE_INTEGER due; due.QuadPart = -(scheduled - sleep_begin) * 10000000 / frequency.QuadPart;
            if (!due.QuadPart) due.QuadPart = -1;
            if (!SetWaitableTimer(timer, &due, 0, NULL, NULL, FALSE) || WaitForSingleObject(timer, INFINITE) != WAIT_OBJECT_0) { result = 1; break; }
        }
        int64_t frame_start = tick(), submit_qpc = 0;
        double sleep_ms = ms(frame_start - sleep_begin), fence_ms = 0, acquire_ms = 0, submit_ms = 0, present_ms = 0;
        add(&sleep_metric, sleep_ms);
        uint32_t slot = (uint32_t)(frames % SLOTS), image = UINT32_MAX;
        Frame *f = &frame[slot];
        VkResult fence_result, acquire_result = VK_NOT_READY, submit_result = VK_NOT_READY, present_result = VK_NOT_READY;
        int64_t begin = tick();
        fence_result = vkWaitForFences(device, 1, &f->fence, VK_TRUE, UINT64_MAX);
        fence_ms = ms(tick() - begin); add(&fence_metric, fence_ms);
        if (fence_result == VK_SUCCESS) {
            begin = tick(); acquire_result = vkAcquireNextImageKHR(device, swapchain, UINT64_MAX, f->acquired, VK_NULL_HANDLE, &image);
            acquire_ms = ms(tick() - begin); add(&acquire_metric, acquire_ms);
        }
        if (acquire_result == VK_SUCCESS || acquire_result == VK_SUBOPTIMAL_KHR) {
            /* Fence reset happens only after successful acquisition, never on an acquisition failure. */
            VkCommandBufferBeginInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
            if (!success(vkResetFences(device, 1, &f->fence), "vkResetFences") || !success(vkResetCommandBuffer(f->command, 0), "vkResetCommandBuffer") || !success(vkBeginCommandBuffer(f->command, &cbi), "vkBeginCommandBuffer")) { result = 1; break; }
            VkImageMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = images[image],
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
            vkCmdPipelineBarrier(f->command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &barrier);
            float phase = (float)(frames % 600) / 600.0f;
            VkClearColorValue color = {{0.08f + 0.25f * phase, 0.12f, 0.35f - 0.25f * phase, 1.0f}};
            vkCmdClearColorImage(f->command, images[image], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &color, 1, &barrier.subresourceRange);
            barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; barrier.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
            barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; barrier.dstAccessMask = 0;
            vkCmdPipelineBarrier(f->command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, NULL, 0, NULL, 1, &barrier);
            if (!success(vkEndCommandBuffer(f->command), "vkEndCommandBuffer")) { result = 1; break; }
            VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
            VkSubmitInfo submission = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .waitSemaphoreCount = 1, .pWaitSemaphores = &f->acquired,
                .pWaitDstStageMask = &wait_stage, .commandBufferCount = 1, .pCommandBuffers = &f->command, .signalSemaphoreCount = 1, .pSignalSemaphores = &ready[image]};
            submit_qpc = tick(); submit_result = vkQueueSubmit(queue, 1, &submission, f->fence);
            submit_ms = ms(tick() - submit_qpc); add(&submit_metric, submit_ms);
            if (submit_result == VK_SUCCESS) {
                VkPresentInfoKHR presentation = {.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, .waitSemaphoreCount = 1, .pWaitSemaphores = &ready[image], .swapchainCount = 1, .pSwapchains = &swapchain, .pImageIndices = &image};
                begin = tick(); present_result = vkQueuePresentKHR(queue, &presentation);
                present_ms = ms(tick() - begin); add(&present_metric, present_ms);
            }
        }
        ++attempts;
        int valid = fence_result == VK_SUCCESS && (acquire_result == VK_SUCCESS || acquire_result == VK_SUBOPTIMAL_KHR) && submit_result == VK_SUCCESS && (present_result == VK_SUCCESS || present_result == VK_SUBOPTIMAL_KHR);
        int64_t end = tick();
        ++schedule_tick;
        uint64_t next_tick = (uint64_t)(end - epoch) * target_fps / (uint64_t)frequency.QuadPart + 1;
        if (next_tick > schedule_tick) { deadline_skips += next_tick - schedule_tick; schedule_tick = next_tick; }
        if (csv) fprintf(csv, "%llu,%u,%u,%lld,%lld,%lld,%lld,%lld,%lld,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%d,%d,%d,%llu\n",
            (unsigned long long)attempts, slot, image, (long long)scheduled, (long long)sleep_begin, (long long)frame_start, (long long)submit_qpc,
            (long long)end, (long long)frequency.QuadPart, sleep_ms, ms(frame_start - scheduled), fence_ms, acquire_ms, submit_ms, present_ms, ms(end - frame_start),
            fence_result, acquire_result, submit_result, present_result, (unsigned long long)deadline_skips);
        if (!valid) {
            ++drops;
            if (exclusive_acquired && (acquire_result == VK_ERROR_FULL_SCREEN_EXCLUSIVE_MODE_LOST_EXT ||
                                      present_result == VK_ERROR_FULL_SCREEN_EXCLUSIVE_MODE_LOST_EXT)) {
                exclusive_acquired = 0; /* the implementation has already released exclusive ownership */
                fprintf(stderr, "exclusive-lost: frame=%llu acquire=%d present=%d fallback=disabled\n",
                    (unsigned long long)attempts, acquire_result, present_result);
            }
            fprintf(stderr, "Frame failure: fence=%d acquire=%d submit=%d present=%d\n", fence_result, acquire_result, submit_result, present_result);
            result = 1; break;
        }
        ++frames;
        if (frames % 600 == 0) summary(frames, attempts, drops, deadline_skips, ms(end - epoch) / 1000, &fence_metric, &acquire_metric, &submit_metric, &present_metric, &sleep_metric);
    }
    summary(frames, attempts, drops, deadline_skips, ms(tick() - epoch) / 1000, &fence_metric, &acquire_metric, &submit_metric, &present_metric, &sleep_metric);
cleanup:
    if (device) {
        int64_t begin = tick(); VkResult idle = vkDeviceWaitIdle(device);
        printf("cleanup_device_idle_ms=%.3f result=%d\n", ms(tick() - begin), idle);
        if (idle != VK_SUCCESS) result = 1;
        if (exclusive_acquired) {
            VkResult released = release_exclusive(device, swapchain);
            printf("exclusive-release: result=%d\n", released);
            if (released != VK_SUCCESS) result = 1;
            exclusive_acquired = 0;
        }
        for (uint32_t i = 0; i < SLOTS; ++i) { if (frame[i].fence) vkDestroyFence(device, frame[i].fence, NULL); if (frame[i].acquired) vkDestroySemaphore(device, frame[i].acquired, NULL); }
        if (ready) for (uint32_t i = 0; i < image_count; ++i) if (ready[i]) vkDestroySemaphore(device, ready[i], NULL);
        if (pool) vkDestroyCommandPool(device, pool, NULL);
        if (swapchain) vkDestroySwapchainKHR(device, swapchain, NULL);
        vkDestroyDevice(device, NULL);
    }
    if (surface) vkDestroySurfaceKHR(instance, surface, NULL);
    if (instance) vkDestroyInstance(instance, NULL);
    if (timer) CloseHandle(timer);
    if (window && IsWindow(window)) DestroyWindow(window);
    UnregisterClassW(L"DiabloVulkanPresentProbe", module);
    if (csv && fclose(csv)) { perror("CSV close"); result = 1; }
    free(ready); free(images); free(present_modes); free(formats); free(physical);
    return result;
}
