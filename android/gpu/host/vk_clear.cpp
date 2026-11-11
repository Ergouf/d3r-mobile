// Solid-colour present path for M1.
//
// Creates the same instance/device as d3_vk_probe, then a swapchain on the
// ANativeWindow and clears the acquired image to a fixed colour before
// presenting it.  This is deliberately independent of Eden's renderer: it only
// proves "window -> swapchain -> clear -> present" on the device, which is the
// floor the renderer will later reuse.
#include <android/log.h>

#include <cstdarg>
#include <cstring>
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

void ClearReport(const char* format, ...) {
    va_list args;
    va_start(args, format);
    __android_log_vprint(ANDROID_LOG_INFO, "d3gpu", format, args);
    va_end(args);
}

} // namespace

extern "C" __attribute__((visibility("default"))) int d3_vk_clear(void* native_window) {
    if (!native_window) {
        ClearReport("vk-clear: no window");
        return -1;
    }

    try {
        auto library = Vulkan::OpenLibrary();
        Vulkan::vk::InstanceDispatch idld;
        auto instance = Vulkan::CreateInstance(*library, idld, VK_API_VERSION_1_2,
                                               Core::Frontend::WindowSystemType::Android);
        auto& dispatch = instance.Dispatch();

        u32 physical_count = 0;
        dispatch.vkEnumeratePhysicalDevices(*instance, &physical_count, nullptr);
        std::vector<VkPhysicalDevice> physical_devices(physical_count);
        dispatch.vkEnumeratePhysicalDevices(*instance, &physical_count, physical_devices.data());

        Core::Frontend::EmuWindow::WindowSystemInfo window_info{};
        window_info.type = Core::Frontend::WindowSystemType::Android;
        window_info.render_surface = native_window;
        // Keep the owning wrapper alive: vk::SurfaceKHR destroys the surface in
        // its destructor, so dereferencing a temporary would leave us with a
        // dangling handle.
        const auto surface_owner = Vulkan::CreateSurface(instance, window_info);
        const VkSurfaceKHR surface = *surface_owner;

        const Vulkan::vk::PhysicalDevice physical{physical_devices[0], dispatch};
        Vulkan::Device device{*instance, physical, surface, dispatch};
        const auto& dev = device.GetDispatchLoader();
        const VkDevice logical = *device.GetLogical();

        VkSurfaceCapabilitiesKHR caps{};
        dispatch.vkGetPhysicalDeviceSurfaceCapabilitiesKHR(physical, surface, &caps);

        VkSurfaceFormatKHR format{VK_FORMAT_B8G8R8A8_UNORM, VK_COLOR_SPACE_SRGB_NONLINEAR_KHR};
        u32 format_count = 0;
        dispatch.vkGetPhysicalDeviceSurfaceFormatsKHR(physical, surface, &format_count, nullptr);
        std::vector<VkSurfaceFormatKHR> formats(format_count);
        dispatch.vkGetPhysicalDeviceSurfaceFormatsKHR(physical, surface, &format_count,
                                                      formats.data());
        if (format_count > 0) {
            format = formats[0];
            for (const auto& candidate : formats) {
                if (candidate.format == VK_FORMAT_B8G8R8A8_UNORM ||
                    candidate.format == VK_FORMAT_R8G8B8A8_UNORM) {
                    format = candidate;
                    break;
                }
            }
        }

        VkExtent2D extent = caps.currentExtent;
        if (extent.width == UINT32_MAX || extent.height == UINT32_MAX) {
            extent = caps.maxImageExtent;
        }

        VkSwapchainCreateInfoKHR swapchain_info{};
        swapchain_info.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
        swapchain_info.surface = surface;
        swapchain_info.minImageCount = caps.minImageCount;
        swapchain_info.imageFormat = format.format;
        swapchain_info.imageColorSpace = format.colorSpace;
        swapchain_info.imageExtent = extent;
        swapchain_info.imageArrayLayers = 1;
        swapchain_info.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
        swapchain_info.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
        swapchain_info.preTransform = caps.currentTransform;
        swapchain_info.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
        swapchain_info.presentMode = VK_PRESENT_MODE_FIFO_KHR;
        swapchain_info.clipped = VK_TRUE;

        VkSwapchainKHR swapchain = VK_NULL_HANDLE;
        VkResult result = dev.vkCreateSwapchainKHR(logical, &swapchain_info, nullptr, &swapchain);
        if (result != VK_SUCCESS) {
            ClearReport("vk-clear: vkCreateSwapchainKHR failed (%d)", static_cast<int>(result));
            return -2;
        }

        u32 image_count = 0;
        dev.vkGetSwapchainImagesKHR(logical, swapchain, &image_count, nullptr);
        std::vector<VkImage> images(image_count);
        dev.vkGetSwapchainImagesKHR(logical, swapchain, &image_count, images.data());
        ClearReport("vk-clear: swapchain %ux%u format=%u images=%u", extent.width, extent.height,
                    static_cast<unsigned>(format.format), image_count);

        VkCommandPoolCreateInfo pool_info{};
        pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        pool_info.queueFamilyIndex = device.GetGraphicsFamily();
        VkCommandPool pool = VK_NULL_HANDLE;
        if (dev.vkCreateCommandPool(logical, &pool_info, nullptr, &pool) != VK_SUCCESS) {
            ClearReport("vk-clear: vkCreateCommandPool failed");
            return -3;
        }

        VkCommandBufferAllocateInfo buffer_info{};
        buffer_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        buffer_info.commandPool = pool;
        buffer_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        buffer_info.commandBufferCount = 1;
        VkCommandBuffer command = VK_NULL_HANDLE;
        dev.vkAllocateCommandBuffers(logical, &buffer_info, &command);

        VkSemaphoreCreateInfo semaphore_info{};
        semaphore_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
        VkSemaphore acquired = VK_NULL_HANDLE;
        VkSemaphore rendered = VK_NULL_HANDLE;
        dev.vkCreateSemaphore(logical, &semaphore_info, nullptr, &acquired);
        dev.vkCreateSemaphore(logical, &semaphore_info, nullptr, &rendered);
        VkFenceCreateInfo fence_info{};
        fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        VkFence fence = VK_NULL_HANDLE;
        dev.vkCreateFence(logical, &fence_info, nullptr, &fence);

        u32 image_index = 0;
        result = dev.vkAcquireNextImageKHR(logical, swapchain, UINT64_MAX, acquired, VK_NULL_HANDLE,
                                           &image_index);
        if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR) {
            ClearReport("vk-clear: vkAcquireNextImageKHR failed (%d)", static_cast<int>(result));
            return -4;
        }

        VkCommandBufferBeginInfo begin{};
        begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        dev.vkBeginCommandBuffer(command, &begin);

        VkImageMemoryBarrier to_clear{};
        to_clear.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        to_clear.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        to_clear.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        to_clear.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        to_clear.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        to_clear.image = images[image_index];
        to_clear.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        to_clear.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        dev.vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                                 VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1,
                                 &to_clear);

        VkClearColorValue colour{};
        colour.float32[0] = 0.05f;
        colour.float32[1] = 0.35f;
        colour.float32[2] = 0.85f;
        colour.float32[3] = 1.0f;
        const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        dev.vkCmdClearColorImage(command, images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                                 &colour, 1, &range);

        VkImageMemoryBarrier to_present = to_clear;
        to_present.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        to_present.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
        to_present.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        to_present.dstAccessMask = 0;
        dev.vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT,
                                 VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, nullptr, 0, nullptr, 1,
                                 &to_present);

        dev.vkEndCommandBuffer(command);

        VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
        VkSubmitInfo submit{};
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit.waitSemaphoreCount = 1;
        submit.pWaitSemaphores = &acquired;
        submit.pWaitDstStageMask = &wait_stage;
        submit.commandBufferCount = 1;
        submit.pCommandBuffers = &command;
        submit.signalSemaphoreCount = 1;
        submit.pSignalSemaphores = &rendered;
        result = device.GetGraphicsQueue().Submit({&submit, 1}, fence);
        if (result != VK_SUCCESS) {
            ClearReport("vk-clear: vkQueueSubmit failed (%d)", static_cast<int>(result));
            return -5;
        }
        dev.vkWaitForFences(logical, 1, &fence, VK_TRUE, UINT64_MAX);

        VkPresentInfoKHR present{};
        present.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
        present.waitSemaphoreCount = 1;
        present.pWaitSemaphores = &rendered;
        present.swapchainCount = 1;
        present.pSwapchains = &swapchain;
        present.pImageIndices = &image_index;
        result = device.GetPresentQueue().Present(present);

        ClearReport("vk-clear: presented image %u result=%d", image_index,
                    static_cast<int>(result));
        return result == VK_SUCCESS ? 0 : -6;
    } catch (const std::exception& exception) {
        ClearReport("vk-clear: failed: %s", exception.what());
        return -7;
    } catch (...) {
        ClearReport("vk-clear: failed with an unknown error");
        return -8;
    }
}
