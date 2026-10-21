/* SPDX-License-Identifier: GPL-3.0-or-later
   Copyright 2026 the ScarletNX contributors */
/* Vulkan clear through the pinned CC0 vk_dxgi library: same-adapter D3D12 resources/fence,
   DXGI FLIP_DISCARD presentation, no game data, CPU pixel readback, or display-mode changes.
   Dependency: local/tools/vk-dxgi (SOURCE.json pins commit and hashes; LICENSE is CC0-1.0).
   Build with tools/windows-dev/Build-VkDxgiPresentProbe.ps1. It keeps the pinned upstream header
   unchanged and generates a MinGW enum-forward-declaration compatibility header under out/windows.
   Equivalent compiler invocation after generating that header:
     clang++ -std=c++20 -O2 -Wall -Wextra -Werror -isystem out/windows/vk-dxgi-compat \
       tools/windows-dev/vk-dxgi-present-probe.cpp -o out/windows/vk-dxgi-present-probe.exe \
       -lvulkan-1 -ld3d12 -ldxgi -ldxguid -luser32
   --check-only creates/validates interop resources but submits no rendering.
   Frame CSV and host_present_fps measure host API timing, NOT actual displayed FPS. */
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_USE_PLATFORM_WIN32_KHR
#include <windows.h>
#define DX_SWAP_VK_IMPLEMENTATION
#include <vk_dxgi.h>
#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <malloc.h>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif
static LARGE_INTEGER frequency;
static bool closing;
static int64_t tick() { LARGE_INTEGER value; QueryPerformanceCounter(&value); return value.QuadPart; }
static double ms(int64_t value) { return static_cast<double>(value) * 1000.0 / frequency.QuadPart; }
static void vk_check(VkResult result, const char *operation) {
    if (result != VK_SUCCESS) throw std::runtime_error(std::string(operation) + " VkResult=" + std::to_string(result));
}
static void dvk_check(const dvk_result_t &result, const char *operation) {
    if (dvk_isError(result)) throw std::runtime_error(std::string(operation) + " code=" + std::to_string(result.code) + " " + result.message);
}
struct Metric {
    double sum = 0, max = 0;
    uint64_t over20 = 0;
    void add(double value) { sum += value; max = std::max(max, value); over20 += value > 20.0; }
    void print(const char *name) const {
        printf(" %s_sum_ms=%.3f %s_max_ms=%.3f %s_gt20=%llu", name, sum, name, max, name,
               static_cast<unsigned long long>(over20));
    }
};
static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_CLOSE) { closing = true; DestroyWindow(window); return 0; }
    if (message == WM_DESTROY) { closing = true; PostQuitMessage(0); return 0; }
    if (message == WM_PAINT) { ValidateRect(window, nullptr); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}
static void pump() {
    MSG message;
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
        if (message.message == WM_QUIT) closing = true;
        TranslateMessage(&message); DispatchMessageW(&message);
    }
}
static const char *arg_value(int &index, int argc, char **argv, const char *name) {
    size_t length = strlen(name);
    if (!strncmp(argv[index], name, length) && argv[index][length] == '=') return argv[index] + length + 1;
    if (!strcmp(argv[index], name) && index + 1 < argc) return argv[++index];
    return nullptr;
}
static unsigned unsigned_arg(const char *value, unsigned low, unsigned high) {
    char *end = nullptr;
    errno = 0;
    unsigned long number = strtoul(value, &end, 10);
    if (!*value || *value == '-' || errno || *end || number < low || number > high)
        throw std::runtime_error(std::string("Invalid unsigned argument: ") + value);
    return static_cast<unsigned>(number);
}
static void *allocate(size_t size, size_t alignment, void *) { return _aligned_malloc(size, alignment); }
static void deallocate(void *address, void *) { _aligned_free(address); }

struct Probe {
    HWND window = nullptr;
    VkInstance instance = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    uint32_t family = UINT32_MAX;
    VkPhysicalDeviceProperties properties = {};
    VkCommandPool pool = VK_NULL_HANDLE;
    struct Frame { VkFence fence = VK_NULL_HANDLE; VkCommandBuffer command = VK_NULL_HANDLE; } frames[2];
    dvk_functions_t functions = {};
    dvk_vulkanContext_t context = {};
    dvk_dxgiDeviceContext_t dxgi = {};
    dvk_dxgiSwapChain_t swap = {};
    dvk_allocator_t allocator = {allocate, deallocate, nullptr};
    bool dxgi_ready = false, swap_ready = false, image_used = false, wait_for_focus = false;
    HANDLE timer = nullptr;
    FILE *csv = nullptr;
    unsigned width = 0, height = 0, fps = 60, sync_interval = 1;
    double seconds = 30.0;
    uint64_t frame_count = 0, attempts = 0, failures = 0, skips = 0;
    Metric fence_metric, acquire_metric, record_metric, submit_metric, present_metric, sleep_metric;

    ~Probe() {
        if (device) {
            int64_t start = tick();
            VkResult result = vkDeviceWaitIdle(device);
            printf("cleanup_device_idle_ms=%.3f result=%d\n", ms(tick() - start), result);
            if (swap_ready) dvk_destroySwapChain(&swap);
            if (dxgi_ready) dvk_destroyDevice(dxgi);
            for (auto &frame : frames) if (frame.fence) vkDestroyFence(device, frame.fence, nullptr);
            if (pool) vkDestroyCommandPool(device, pool, nullptr);
            vkDestroyDevice(device, nullptr);
        }
        if (instance) vkDestroyInstance(instance, nullptr);
        if (timer) CloseHandle(timer);
        if (csv && fclose(csv)) perror("CSV close");
        if (window && IsWindow(window)) DestroyWindow(window);
        UnregisterClassW(L"DiabloVkDxgiPresentProbe", GetModuleHandleW(nullptr));
    }
    void init() {
        SetProcessDPIAware();
        if (!width) width = GetSystemMetrics(SM_CXSCREEN);
        if (!height) height = GetSystemMetrics(SM_CYSCREEN);
        WNDCLASSW wc = {};
        wc.lpfnWndProc = window_proc; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"DiabloVkDxgiPresentProbe";
        wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
        if (!RegisterClassW(&wc)) throw std::runtime_error("RegisterClassW failed");
        wchar_t title[128];
        swprintf(title, sizeof title / sizeof title[0], L"Vulkan-DXGI Present Probe - %u FPS clear", fps);
        window = CreateWindowExW(0, wc.lpszClassName, title, WS_POPUP, 0, 0, width, height, nullptr, nullptr, wc.hInstance, nullptr);
        if (!window) throw std::runtime_error("CreateWindowExW failed");
        ShowWindow(window, SW_SHOW); UpdateWindow(window);

        VkApplicationInfo app = {};
        app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO; app.pApplicationName = "Vulkan-DXGI clear/present probe"; app.apiVersion = VK_API_VERSION_1_3;
        VkInstanceCreateInfo instance_info = {};
        instance_info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO; instance_info.pApplicationInfo = &app;
        vk_check(vkCreateInstance(&instance_info, nullptr, &instance), "vkCreateInstance");
        uint32_t count = 0;
        vk_check(vkEnumeratePhysicalDevices(instance, &count, nullptr), "enumerate Vulkan device count");
        std::vector<VkPhysicalDevice> candidates(count);
        vk_check(vkEnumeratePhysicalDevices(instance, &count, candidates.data()), "enumerate Vulkan devices");
        LUID luid = {};
        for (int pass = 0; pass < 2 && !physical; ++pass) for (VkPhysicalDevice candidate : candidates) {
            VkPhysicalDeviceIDProperties id = {}; id.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
            VkPhysicalDeviceProperties2 props = {}; props.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2; props.pNext = &id;
            vkGetPhysicalDeviceProperties2(candidate, &props);
            if (props.properties.apiVersion < VK_API_VERSION_1_3 || !id.deviceLUIDValid || (pass == 0 && props.properties.vendorID != 0x8086)) continue;
            uint32_t queue_count = 0;
            vkGetPhysicalDeviceQueueFamilyProperties(candidate, &queue_count, nullptr);
            std::vector<VkQueueFamilyProperties> queues(queue_count);
            vkGetPhysicalDeviceQueueFamilyProperties(candidate, &queue_count, queues.data());
            for (uint32_t index = 0; index < queue_count; ++index) if (queues[index].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
                physical = candidate; family = index; properties = props.properties;
                static_assert(sizeof luid == VK_LUID_SIZE);
                memcpy(&luid, id.deviceLUID, sizeof luid); break;
            }
            if (physical) break;
        }
        if (!physical) throw std::runtime_error("Unsupported: no Vulkan1.3 graphics device with valid adapter LUID");
        vk_check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, nullptr), "enumerate device extension count");
        std::vector<VkExtensionProperties> extensions(count);
        vk_check(vkEnumerateDeviceExtensionProperties(physical, nullptr, &count, extensions.data()), "enumerate device extensions");
        for (const char *required : dvk_required_vulkan_extensions) {
            bool found = std::any_of(extensions.begin(), extensions.end(), [required](const auto &extension) { return !strcmp(required, extension.extensionName); });
            printf("interop-capability: extension=%s supported=%d\n", required, found);
            if (!found) throw std::runtime_error(std::string("Unsupported required extension: ") + required);
        }
        VkPhysicalDeviceTimelineSemaphoreFeatures timeline = {}; timeline.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES;
        VkPhysicalDeviceFeatures2 features = {}; features.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2; features.pNext = &timeline;
        vkGetPhysicalDeviceFeatures2(physical, &features);
        if (!timeline.timelineSemaphore) throw std::runtime_error("Unsupported: timelineSemaphore feature");
        VkPhysicalDeviceExternalImageFormatInfo external_image = {};
        external_image.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_IMAGE_FORMAT_INFO; external_image.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE_BIT;
        VkPhysicalDeviceImageFormatInfo2 image_info = {};
        image_info.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_FORMAT_INFO_2; image_info.pNext = &external_image;
        image_info.format = VK_FORMAT_B8G8R8A8_UNORM; image_info.type = VK_IMAGE_TYPE_2D; image_info.tiling = VK_IMAGE_TILING_OPTIMAL;
        image_info.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        VkExternalImageFormatProperties external_properties = {}; external_properties.sType = VK_STRUCTURE_TYPE_EXTERNAL_IMAGE_FORMAT_PROPERTIES;
        VkImageFormatProperties2 image_properties = {}; image_properties.sType = VK_STRUCTURE_TYPE_IMAGE_FORMAT_PROPERTIES_2; image_properties.pNext = &external_properties;
        vk_check(vkGetPhysicalDeviceImageFormatProperties2(physical, &image_info, &image_properties), "query BGRA8 D3D12_RESOURCE import");
        auto memory_features = external_properties.externalMemoryProperties.externalMemoryFeatures;
        printf("interop-capability: D3D12_RESOURCE_BGRA8_externalMemoryFeatures=0x%x\n", memory_features);
        if (!(memory_features & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT)) throw std::runtime_error("Unsupported: BGRA8 D3D12 resource import");
        VkSemaphoreTypeCreateInfo semaphore_type = {}; semaphore_type.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO; semaphore_type.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
        VkPhysicalDeviceExternalSemaphoreInfo semaphore_info = {}; semaphore_info.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_SEMAPHORE_INFO;
        semaphore_info.pNext = &semaphore_type; semaphore_info.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_D3D12_FENCE_BIT;
        VkExternalSemaphoreProperties semaphore_properties = {}; semaphore_properties.sType = VK_STRUCTURE_TYPE_EXTERNAL_SEMAPHORE_PROPERTIES;
        vkGetPhysicalDeviceExternalSemaphoreProperties(physical, &semaphore_info, &semaphore_properties);
        printf("interop-capability: D3D12_FENCE_timeline_externalSemaphoreFeatures=0x%x\n", semaphore_properties.externalSemaphoreFeatures);
        if (!(semaphore_properties.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT)) throw std::runtime_error("Unsupported: D3D12 fence timeline import");

        float priority = 1;
        VkDeviceQueueCreateInfo queue_info = {}; queue_info.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
        queue_info.queueFamilyIndex = family; queue_info.queueCount = 1; queue_info.pQueuePriorities = &priority;
        VkDeviceCreateInfo device_info = {}; device_info.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO; device_info.pNext = &timeline;
        device_info.queueCreateInfoCount = 1; device_info.pQueueCreateInfos = &queue_info;
        device_info.enabledExtensionCount = static_cast<uint32_t>(sizeof dvk_required_vulkan_extensions / sizeof dvk_required_vulkan_extensions[0]);
        device_info.ppEnabledExtensionNames = dvk_required_vulkan_extensions;
        vk_check(vkCreateDevice(physical, &device_info, nullptr, &device), "vkCreateDevice");
        vkGetDeviceQueue(device, family, 0, &queue);
        functions.pCreateFactory = CreateDXGIFactory2; functions.pCreateDevice = D3D12CreateDevice; functions.pGetDebugInterface = D3D12GetDebugInterface;
        functions.vkCreateImage = vkCreateImage; functions.vkGetImageMemoryRequirements = vkGetImageMemoryRequirements;
        functions.vkGetPhysicalDeviceMemoryProperties = vkGetPhysicalDeviceMemoryProperties; functions.vkAllocateMemory = vkAllocateMemory;
        functions.vkBindImageMemory = vkBindImageMemory; functions.vkCreateSemaphore = vkCreateSemaphore;
        functions.vkDestroyImage = vkDestroyImage; functions.vkFreeMemory = vkFreeMemory; functions.vkDestroySemaphore = vkDestroySemaphore; functions.vkDeviceWaitIdle = vkDeviceWaitIdle;
        functions.vkGetMemoryWin32HandlePropertiesKHR = reinterpret_cast<PFN_vkGetMemoryWin32HandlePropertiesKHR>(vkGetDeviceProcAddr(device, "vkGetMemoryWin32HandlePropertiesKHR"));
        functions.vkImportSemaphoreWin32HandleKHR = reinterpret_cast<PFN_vkImportSemaphoreWin32HandleKHR>(vkGetDeviceProcAddr(device, "vkImportSemaphoreWin32HandleKHR"));
        if (!functions.vkGetMemoryWin32HandlePropertiesKHR || !functions.vkImportSemaphoreWin32HandleKHR) throw std::runtime_error("Required interop entry points unavailable");
        context.physicalDevice = physical; context.device = device;
        dvk_createDeviceParameters_t dxgi_parameters = {}; dxgi_parameters.pFunctions = &functions; dxgi_parameters.deviceLuid = luid;
        dvk_check(dvk_createDevice(dxgi_parameters, &dxgi), "dvk_createDevice"); dxgi_ready = true;
        LUID actual_luid = dxgi.pD3D12Device->GetAdapterLuid();
        if (memcmp(&actual_luid, &luid, sizeof luid)) throw std::runtime_error("DXGI/Vulkan adapter LUID mismatch");
        dvk_createSwapChainParameters_t swap_parameters = {};
        swap_parameters.pFunctions = &functions; swap_parameters.pAllocator = &allocator; swap_parameters.pDeviceContext = &dxgi; swap_parameters.pVulkanContext = &context;
        swap_parameters.window = window; swap_parameters.width = static_cast<uint16_t>(width); swap_parameters.height = static_cast<uint16_t>(height);
        swap_parameters.format = VK_FORMAT_B8G8R8A8_UNORM; swap_parameters.usage = image_info.usage;
        swap_parameters.imageCount = 3; swap_parameters.maximumLatency = 1; swap_parameters.syncInterval = sync_interval; swap_parameters.flags = DVK_SWAPCHAIN_BACKBUFFER_BLIT_FLAG;
        dvk_check(dvk_createSwapChain(swap_parameters, &swap), "dvk_createSwapChain"); swap_ready = true;
        VkCommandPoolCreateInfo pool_info = {}; pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT; pool_info.queueFamilyIndex = family;
        vk_check(vkCreateCommandPool(device, &pool_info, nullptr, &pool), "vkCreateCommandPool");
        for (auto &frame : frames) {
            VkFenceCreateInfo fence_info = {}; fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO; fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;
            vk_check(vkCreateFence(device, &fence_info, nullptr, &frame.fence), "vkCreateFence");
            VkCommandBufferAllocateInfo command_info = {}; command_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
            command_info.commandPool = pool; command_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; command_info.commandBufferCount = 1;
            vk_check(vkAllocateCommandBuffers(device, &command_info, &frame.command), "vkAllocateCommandBuffers");
        }
        printf("gpu=%s driver_raw=%u extent=%ux%u format=BGRA8_UNORM mode=DXGI_FLIP_DISCARD_BLIT sync_interval=%u target_fps=%u image_count=3 frame_slots=2 maximum_latency=1 luid=%08lx:%08lx\n",
            properties.deviceName, properties.driverVersion, width, height, sync_interval, fps, static_cast<unsigned long>(luid.HighPart), static_cast<unsigned long>(luid.LowPart));
        fflush(stdout);
    }
    void summary(double elapsed) const {
        printf("frames=%llu attempts=%llu api_failures=%llu deadline_skips=%llu elapsed_s=%.3f host_present_fps=%.3f",
            static_cast<unsigned long long>(frame_count), static_cast<unsigned long long>(attempts), static_cast<unsigned long long>(failures),
            static_cast<unsigned long long>(skips), elapsed, elapsed > 0 ? frame_count / elapsed : 0);
        fence_metric.print("fence"); acquire_metric.print("acquire"); record_metric.print("record"); submit_metric.print("submit");
        present_metric.print("present"); sleep_metric.print("limiter_wait"); putchar('\n'); fflush(stdout);
    }
    void run(const char *output) {
        if (wait_for_focus) {
            printf("await-focus: hwnd=%p timeout_ms=30000\n", static_cast<void *>(window)); fflush(stdout);
            int64_t start = tick();
            while (!closing && GetForegroundWindow() != window && ms(tick() - start) < 30000.0) {
                pump();
                if (!closing && GetForegroundWindow() != window) Sleep(10);
            }
            if (closing || GetForegroundWindow() != window) throw std::runtime_error("Foreground activation timed out or probe window closed");
        }
        if (output) {
            csv = fopen(output, "wb"); if (!csv) throw std::runtime_error("Cannot open output CSV");
            setvbuf(csv, nullptr, _IOFBF, 1 << 20);
            fputs("frame,slot,image,scheduled_qpc,limiter_begin_qpc,frame_start_qpc,submit_qpc,frame_end_qpc,qpc_frequency,limiter_wait_ms,start_late_ms,fence_wait_ms,acquire_ms,record_ms,submit_ms,present_ms,cpu_frame_ms,fence_result,acquire_code,submit_result,present_code,deadline_skips_total,wait_value,submit_value,blit_value\n", csv);
        }
        timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
        bool high_resolution = timer != nullptr;
        if (!timer) timer = CreateWaitableTimerExW(nullptr, nullptr, 0, TIMER_ALL_ACCESS);
        if (!timer) throw std::runtime_error("CreateWaitableTimerExW failed");
        printf("high_resolution_timer=%d qpc_frequency=%lld seconds=%.3f hwnd=%p foreground_at_start=%d\n", high_resolution,
            static_cast<long long>(frequency.QuadPart), seconds, static_cast<void *>(window), GetForegroundWindow() == window); fflush(stdout);
        int64_t epoch = tick(); uint64_t schedule_tick = 0;
        try {
            while (!closing) {
                pump(); if (closing || ms(tick() - epoch) >= seconds * 1000.0) break;
                int64_t scheduled = epoch + static_cast<int64_t>(schedule_tick * static_cast<uint64_t>(frequency.QuadPart) / fps);
                int64_t sleep_begin = tick();
                if (scheduled > sleep_begin) {
                    LARGE_INTEGER due; due.QuadPart = -(scheduled - sleep_begin) * 10000000 / frequency.QuadPart;
                    if (!due.QuadPart) due.QuadPart = -1;
                    if (!SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE) || WaitForSingleObject(timer, INFINITE) != WAIT_OBJECT_0)
                        throw std::runtime_error("limiter wait failed");
                }
                int64_t frame_start = tick(); double sleep_ms = ms(frame_start - sleep_begin); sleep_metric.add(sleep_ms);
                ++attempts;
                unsigned slot = static_cast<unsigned>(frame_count % 2); auto &frame = frames[slot];
                int64_t start = tick(); VkResult fence_result = vkWaitForFences(device, 1, &frame.fence, VK_TRUE, UINT64_MAX);
                double fence_ms = ms(tick() - start); fence_metric.add(fence_ms); vk_check(fence_result, "frame fence");
                dvk_presentationInfo_t presentation = {};
                start = tick(); dvk_result_t acquired = dvk_acquireImage(&swap, &presentation);
                double acquire_ms = ms(tick() - start); acquire_metric.add(acquire_ms); dvk_check(acquired, "dvk_acquireImage");
                start = tick();
                vk_check(vkResetFences(device, 1, &frame.fence), "vkResetFences");
                vk_check(vkResetCommandBuffer(frame.command, 0), "vkResetCommandBuffer");
                VkCommandBufferBeginInfo begin = {}; begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO; begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
                vk_check(vkBeginCommandBuffer(frame.command, &begin), "vkBeginCommandBuffer");
                // The D3D12 COMMON state is handed across APIs using Vulkan GENERAL layout.
                // Discard only on the first use, and release ownership before D3D12 reads the resource.
                VkImageMemoryBarrier barrier = {}; barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
                barrier.oldLayout = image_used ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_UNDEFINED; barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
                barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL; barrier.dstQueueFamilyIndex = family;
                barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; barrier.image = swap.vkBlitImage;
                barrier.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
                vkCmdPipelineBarrier(frame.command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
                float phase = static_cast<float>(frame_count % 600) / 600.0f;
                VkClearColorValue color = {{0.08f + 0.25f * phase, 0.12f, 0.35f - 0.25f * phase, 1.0f}};
                vkCmdClearColorImage(frame.command, swap.vkBlitImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &color, 1, &barrier.subresourceRange);
                barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
                barrier.srcQueueFamilyIndex = family; barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL;
                barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; barrier.dstAccessMask = 0;
                vkCmdPipelineBarrier(frame.command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, nullptr, 0, nullptr, 1, &barrier);
                vk_check(vkEndCommandBuffer(frame.command), "vkEndCommandBuffer");
                double record_ms = ms(tick() - start); record_metric.add(record_ms);
                VkTimelineSemaphoreSubmitInfo timeline = {}; timeline.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
                timeline.waitSemaphoreValueCount = 1; timeline.pWaitSemaphoreValues = &presentation.waitValue;
                timeline.signalSemaphoreValueCount = 1; timeline.pSignalSemaphoreValues = &presentation.submitValue;
                VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
                VkSubmitInfo submit = {}; submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO; submit.pNext = &timeline;
                submit.waitSemaphoreCount = 1; submit.pWaitSemaphores = &presentation.waitSemaphore; submit.pWaitDstStageMask = &wait_stage;
                submit.commandBufferCount = 1; submit.pCommandBuffers = &frame.command;
                submit.signalSemaphoreCount = 1; submit.pSignalSemaphores = &presentation.submitSemaphore;
                int64_t submit_qpc = tick(); VkResult submit_result = vkQueueSubmit(queue, 1, &submit, frame.fence);
                double submit_ms = ms(tick() - submit_qpc); submit_metric.add(submit_ms); vk_check(submit_result, "vkQueueSubmit"); image_used = true;
                dvk_presentParameters_t present = {};
                present.pSwapChain = presentation.pSwapChain; present.pCommandQueue = presentation.pCommandQueue;
                present.pCommandList = presentation.pCommandList; present.pFrameResources = presentation.pFrameResources; present.pFence = presentation.pFence;
                present.submitValue = presentation.submitValue; present.blitValue = presentation.blitValue;
                present.allowTearing = presentation.allowTearing; present.syncInterval = presentation.syncInterval;
                start = tick(); dvk_result_t presented = dvk_presentImage(present);
                double present_ms = ms(tick() - start); present_metric.add(present_ms);
                int64_t end = tick(); ++schedule_tick;
                uint64_t next_tick = static_cast<uint64_t>(end - epoch) * fps / static_cast<uint64_t>(frequency.QuadPart) + 1;
                if (next_tick > schedule_tick) { skips += next_tick - schedule_tick; schedule_tick = next_tick; }
                if (csv) fprintf(csv, "%llu,%u,%u,%lld,%lld,%lld,%lld,%lld,%lld,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%d,%d,%d,%llu,%llu,%llu,%llu\n",
                    static_cast<unsigned long long>(attempts), slot, presentation.imageIndex, static_cast<long long>(scheduled), static_cast<long long>(sleep_begin),
                    static_cast<long long>(frame_start), static_cast<long long>(submit_qpc), static_cast<long long>(end), static_cast<long long>(frequency.QuadPart),
                    sleep_ms, ms(frame_start - scheduled), fence_ms, acquire_ms, record_ms, submit_ms, present_ms, ms(end - frame_start),
                    fence_result, acquired.code, submit_result, presented.code, static_cast<unsigned long long>(skips),
                    static_cast<unsigned long long>(presentation.waitValue), static_cast<unsigned long long>(presentation.submitValue), static_cast<unsigned long long>(presentation.blitValue));
                dvk_check(presented, "dvk_presentImage"); ++frame_count;
                if (frame_count % 600 == 0) summary(ms(end - epoch) / 1000.0);
            }
        } catch (...) { ++failures; summary(ms(tick() - epoch) / 1000.0); throw; }
        summary(ms(tick() - epoch) / 1000.0);
        if (csv && (fflush(csv) || ferror(csv))) throw std::runtime_error("CSV flush failed");
    }
};

int main(int argc, char **argv) {
    QueryPerformanceFrequency(&frequency);
    try {
        Probe probe; bool check_only = false; const char *output = nullptr;
        for (int index = 1; index < argc; ++index) {
            const char *value;
            if (!strcmp(argv[index], "--check-only")) check_only = true;
            else if (!strcmp(argv[index], "--wait-for-focus")) probe.wait_for_focus = true;
            else if ((value = arg_value(index, argc, argv, "--seconds"))) {
                char *end = nullptr; errno = 0; probe.seconds = strtod(value, &end);
                if (!*value || errno || *end || !std::isfinite(probe.seconds) || probe.seconds <= 0 || probe.seconds > 3600) throw std::runtime_error("Invalid --seconds");
            } else if ((value = arg_value(index, argc, argv, "--fps"))) probe.fps = unsigned_arg(value, 10, 240);
            else if ((value = arg_value(index, argc, argv, "--sync"))) probe.sync_interval = unsigned_arg(value, 1, 2);
            else if ((value = arg_value(index, argc, argv, "--width"))) probe.width = unsigned_arg(value, 1, 65535);
            else if ((value = arg_value(index, argc, argv, "--height"))) probe.height = unsigned_arg(value, 1, 65535);
            else if ((value = arg_value(index, argc, argv, "--output"))) output = value;
            else throw std::runtime_error(std::string("Unknown/incomplete argument: ") + argv[index]);
        }
        if (check_only && output) throw std::runtime_error("--check-only does not produce a frame CSV; omit --output");
        probe.init();
        if (check_only) { puts("interop-check: status=ready shared_resources=created rendered_frames=0"); return 0; }
        probe.run(output); return 0;
    } catch (const std::exception &error) { fprintf(stderr, "vk-dxgi probe: %s\n", error.what()); return 1; }
}
