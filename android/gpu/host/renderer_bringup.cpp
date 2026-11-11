// Instantiate Eden's Vulkan renderer against the Android surface.
//
// This is the step between the hand-written clear (M1) and the real renderer:
// once this succeeds, framebuffer composites from the guest can go through
// Vulkan::RendererVulkan instead of the temporary clear path.
#include <android/log.h>
#include <unistd.h>

#include <cstdarg>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <exception>
#include <fstream>
#include <memory>
#include <map>
#include <mutex>
#include <thread>
#include <vector>

#include "core/core.h"
#include "gpu_bridge.h"
#include "emu_window_d3.h"
#include "graphics_config.h"
#include "frame_pacing.h"
#include "gpu_backend_policy.h"
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

FILE* FrameTimingLog() {
    static FILE* file = [] {
        const char* path = std::getenv("D3_FRAME_TIMINGS_FILE");
        return path && *path ? std::fopen(path, "w") : nullptr;
    }();
    return file;
}

void RendererReport(const char* format, ...) {
    va_list args;
    va_start(args, format);
    va_list file_args;
    va_copy(file_args, args);
    __android_log_vprint(ANDROID_LOG_INFO, "d3gpu", format, args);
    if (FILE* file = FrameTimingLog()) {
        timespec timestamp{};
        clock_gettime(CLOCK_MONOTONIC, &timestamp);
        flockfile(file);
        std::fprintf(file, "%lld.%09ld %d %d I d3gpu : ",
                     static_cast<long long>(timestamp.tv_sec), timestamp.tv_nsec, getpid(), gettid());
        std::vfprintf(file, format, file_args);
        std::fputc('\n', file);
        static unsigned lines;
        if (++lines % 32 == 0) std::fflush(file);
        funlockfile(file);
    }
    va_end(file_args);
    va_end(args);
}

uint64_t ThreadCpuNanoseconds() {
    timespec value{};
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &value) != 0) return 0;
    return static_cast<uint64_t>(value.tv_sec) * 1000000000ULL + value.tv_nsec;
}

std::unique_ptr<Core::System> g_system;
std::unique_ptr<D3::EmuWindowD3> g_window;
std::unique_ptr<Tegra::MemoryManager> g_address_space;
std::shared_ptr<Tegra::Control::ChannelState> g_channel;
std::mutex g_nv_bridge_mutex;
std::unique_ptr<Tegra::MemoryManager> g_nv_spaces[64];
std::shared_ptr<Tegra::Control::ChannelState> g_nv_channels[64];
std::vector<std::unique_ptr<Tegra::MemoryManager>> g_retired_nv_spaces;
std::map<std::pair<uint32_t, uint64_t>, std::pair<DAddr, uint64_t>> g_nv_mappings;
std::optional<Core::Asid> g_nv_asid;
std::mutex g_present_mutex;
std::condition_variable g_surface_changed;
struct DeviceMapping {
    DAddr address;
    uint64_t size;
    uint32_t references;
};
std::map<std::pair<uint64_t, uint64_t>, DeviceMapping> g_present_mappings;
std::map<uint64_t, DeviceMapping> g_device_mappings;

DAddr AcquireDeviceMapping(uint64_t cpu_address, uint64_t size) {
    const auto backing = reinterpret_cast<uint64_t>(g_system->DeviceMemory().buffer.BackingBasePointer());
    const auto physical = reinterpret_cast<uint64_t>(
        g_system->ApplicationMemory().GetPointer<u8>(Common::ProcessAddress(cpu_address)));
    if (physical < backing || physical - backing >= (8ULL << 30) ||
        size > (8ULL << 30) - (physical - backing))
        return 0;
    const uint64_t offset = physical - backing;
    auto next = g_device_mappings.upper_bound(offset);
    if (next != g_device_mappings.begin()) {
        auto previous = std::prev(next);
        if (offset - previous->first < previous->second.size) {
            if (size > previous->second.size - (offset - previous->first))
                return 0;
            previous->second.references++;
            return previous->second.address + offset - previous->first;
        }
    }
    if (next != g_device_mappings.end() && size > next->first - offset)
        return 0;
    auto& device = g_system->Host1x().memory_manager;
    if (!g_nv_asid)
        g_nv_asid = device.RegisterProcess(&g_system->ApplicationMemory());
    const DAddr address = device.Allocate(size);
    if (!address)
        return 0;
    device.Map(address, cpu_address, size, *g_nv_asid);
    g_device_mappings.emplace(offset, DeviceMapping{address, size, 1});
    return address;
}

void ReleaseDeviceMapping(DAddr address) {
    for (auto mapping = g_device_mappings.begin(); mapping != g_device_mappings.end(); ++mapping) {
        auto& entry = mapping->second;
        if (address < entry.address || address - entry.address >= entry.size)
            continue;
        if (--entry.references == 0) {
            auto& device = g_system->Host1x().memory_manager;
            device.Unmap(entry.address, entry.size);
            device.Free(entry.address, entry.size);
            g_device_mappings.erase(mapping);
        }
        return;
    }
}

} // namespace

extern "C" void d3_gpu_report_cache_scan(uint64_t pages, uint64_t changed, uint64_t elapsed_us,
                                         uint64_t generation, uint64_t faults, uint64_t watch_misses,
                                         uint64_t batch_count, uint64_t batch_total_us, uint64_t batch_max_us,
                                         uint64_t batch_begin_us, uint64_t batch_pages, uint64_t batch_changed,
                                         int cache_mode) {
    RendererReport("cache-scan: pages=%llu changed=%llu us=%llu generation=%llu write-faults=%llu watch-misses=%llu batch_count=%llu batch_total_us=%llu batch_max_us=%llu batch_begin_us=%llu batch_pages=%llu batch_changed=%llu cache_mode=%d",
                   static_cast<unsigned long long>(pages), static_cast<unsigned long long>(changed),
                   static_cast<unsigned long long>(elapsed_us), static_cast<unsigned long long>(generation),
                   static_cast<unsigned long long>(faults), static_cast<unsigned long long>(watch_misses),
                   static_cast<unsigned long long>(batch_count), static_cast<unsigned long long>(batch_total_us),
                   static_cast<unsigned long long>(batch_max_us), static_cast<unsigned long long>(batch_begin_us),
                   static_cast<unsigned long long>(batch_pages), static_cast<unsigned long long>(batch_changed), cache_mode);
}

extern "C" int d3_gpu_import_framebuffer(uint64_t address, uint64_t size) {
    std::scoped_lock present_lock(g_present_mutex);
    std::scoped_lock bridge_lock(g_nv_bridge_mutex);
    if (!g_system || !size || (address & 4095u) || (size & 4095u))
        return -22;
    const DAddr device_address = AcquireDeviceMapping(address, size);
    if (!device_address)
        return -12;
    auto& entry = g_present_mappings[{address, size}];
    entry.address = device_address;
    entry.size = size;
    entry.references++;
    return 0;
}

extern "C" void d3_gpu_release_framebuffer(uint64_t address, uint64_t size) {
    std::scoped_lock present_lock(g_present_mutex);
    std::scoped_lock bridge_lock(g_nv_bridge_mutex);
    const auto mapping = g_present_mappings.find({address, size});
    if (mapping == g_present_mappings.end())
        return;
    ReleaseDeviceMapping(mapping->second.address);
    if (--mapping->second.references == 0)
        g_present_mappings.erase(mapping);
}

extern "C" int d3_gpu_present_guest(uint64_t address, uint64_t size, const uint32_t* buffer,
                                     const uint32_t* queue_input) {
    std::unique_lock present_lock(g_present_mutex);
    static const bool trace_timings = [] {
        const char* value = std::getenv("D3_FRAME_TIMINGS");
        return value && std::strcmp(value, "1") == 0;
    }();
    static std::chrono::steady_clock::time_point last_composite{};
    static const std::string polling_marker = [] {
        const char* path = std::getenv("D3_POLL_FENCES_FILE");
        return std::string(path ? path : "");
    }();
    static uint32_t mode_checks;
    static bool poll_fences;
    static const int configured_cap = [] {
        const char* value = std::getenv("D3_FRAME_CAP");
        const int fps = value ? std::atoi(value) : 60;
        return D3::IsSupportedFrameCap(fps) ? fps : 60;
    }();
    static const std::string cap_marker = [] {
        const char* path = std::getenv("D3_FRAME_CAP_FILE");
        return std::string(path ? path : "");
    }();
    static int frame_cap = configured_cap;
    static D3::FramePacer pacer;
    if (++mode_checks % 32 == 1) {
        int requested_cap = configured_cap;
        if (!cap_marker.empty()) {
            std::ifstream input(cap_marker);
            int override_cap;
            if (input >> override_cap && D3::IsSupportedFrameCap(override_cap)) requested_cap = override_cap;
        }
        if (mode_checks == 1 || requested_cap != frame_cap) {
            frame_cap = requested_cap;
            RendererReport("frame-cap fps=%d", frame_cap);
        }
    }
    if (trace_timings && mode_checks % 32 == 1) {
        const bool requested = !polling_marker.empty() && access(polling_marker.c_str(), F_OK) == 0;
        if (mode_checks == 1 || requested != poll_fences) {
            poll_fences = requested;
            RendererReport("fence-wait-mode polling=%u", static_cast<unsigned>(poll_fences));
        }
    }
    if (g_window && !g_window->IsShown()) last_composite = {};
    g_surface_changed.wait(present_lock, [] { return !g_window || g_window->IsShown(); });
    const auto callback_start = trace_timings ? std::chrono::steady_clock::now()
                                            : std::chrono::steady_clock::time_point{};
    const uint64_t cpu_start = trace_timings ? ThreadCpuNanoseconds() : 0;
    if (!g_system || !buffer || !queue_input || !size || (size & 4095u) ||
        (address & 4095u) || buffer[30] >= size || queue_input[12] > 4)
        return -22;
    auto& syncpoints = g_system->Host1x().GetSyncpointManager();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    for (uint32_t index = 0; index < queue_input[12]; index++) {
        const uint32_t id = queue_input[13 + index * 2];
        const uint32_t value = queue_input[14 + index * 2];
        if (id == UINT32_MAX)
            continue;
        if (id >= 192)
            return -22;
        bool ready;
        if (poll_fences) {
            // Diagnostic control: reproduce the previous algorithm within the same process.
            while (static_cast<int32_t>(syncpoints.GetHostSyncpointValue(id) - value) < 0 &&
                   std::chrono::steady_clock::now() < deadline) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            ready = static_cast<int32_t>(syncpoints.GetHostSyncpointValue(id) - value) >= 0;
        } else {
            ready = syncpoints.WaitHostUntil(id, value, deadline);
        }
        if (!ready) {
            RendererReport("guest-present: fence timeout id=%u target=%u host=%u", id, value,
                           syncpoints.GetHostSyncpointValue(id));
            return -110;
        }
    }
    const auto fences_ready = trace_timings ? std::chrono::steady_clock::now()
                                          : std::chrono::steady_clock::time_point{};
    try {
        DAddr device_address;
        {
            std::scoped_lock bridge_lock(g_nv_bridge_mutex);
            const auto key = std::make_pair(address, size);
            const auto mapping = g_present_mappings.find(key);
            if (mapping == g_present_mappings.end())
                return -22;
            device_address = mapping->second.address;
        }
        Tegra::FramebufferConfig framebuffer{};
        framebuffer.address = device_address;
        framebuffer.offset = buffer[30];
        framebuffer.width = buffer[1];
        framebuffer.height = buffer[2];
        framebuffer.stride = buffer[3];
        framebuffer.pixel_format = static_cast<Service::android::PixelFormat>(buffer[18]);
        framebuffer.transform_flags = static_cast<Service::android::BufferTransformFlags>(queue_input[8]);
        framebuffer.crop_rect = Common::Rectangle<int>{static_cast<int>(queue_input[3]),
            static_cast<int>(queue_input[4]), static_cast<int>(queue_input[5]),
            static_cast<int>(queue_input[6])};
        framebuffer.blending = Tegra::BlendMode::Opaque;
        std::vector<Tegra::FramebufferConfig> layers{framebuffer};
        const auto pacing_start = std::chrono::steady_clock::now();
        std::this_thread::sleep_until(pacer.Deadline(pacing_start, frame_cap));
        const auto present_start = trace_timings ? std::chrono::steady_clock::now()
                                                : std::chrono::steady_clock::time_point{};
        g_system->GPU().RequestComposite(std::move(layers), {});
        const auto wait_start = trace_timings ? std::chrono::steady_clock::now()
                                             : std::chrono::steady_clock::time_point{};
        g_system->GPU().WaitForComposite();
        static uint64_t frames;
        static auto last_report = std::chrono::steady_clock::now();
        static uint64_t last_frames;
        const auto now = std::chrono::steady_clock::now();
        ++frames;
        if (trace_timings) {
            const auto us = [](auto duration) {
                return static_cast<long long>(
                    std::chrono::duration_cast<std::chrono::microseconds>(duration).count());
            };
            const uint64_t cpu_end = ThreadCpuNanoseconds();
            // This wait includes worker/driver/presentation waits, not just GPU execution.
            if (last_composite.time_since_epoch().count() != 0) {
                RendererReport("frame-timing frame=%llu cpu_us=%llu gpu_wait_us=%lld present_us=%lld total_us=%lld frame_interval_us=%lld fence_wait_us=%lld poll_fences=%u cache_mode=%d pacing_wait_us=%lld frame_cap=%d",
                    static_cast<unsigned long long>(frames),
                    static_cast<unsigned long long>(cpu_end >= cpu_start ? (cpu_end - cpu_start) / 1000 : 0),
                    us(now - wait_start), us(now - present_start), us(now - callback_start),
                    us(now - last_composite), us(fences_ready - callback_start),
                    static_cast<unsigned>(poll_fences), d3_gpu_cache_scan_mode(),
                    us(present_start - pacing_start), frame_cap);
            }
            last_composite = now;
        }
        const double elapsed = std::chrono::duration<double>(now - last_report).count();
        if (elapsed >= 5.0) {
            RendererReport("game frames=%llu fps=%.2f interval=%.3fs", (unsigned long long)frames,
                (frames - last_frames) / elapsed, elapsed);
            last_report = now; last_frames = frames;
        }
        if (frames <= 4 || frames % 600 == 0) RendererReport("guest-present: composited %ux%u stride=%u nvmap=%u cpu=%#llx device=%#llx fences=%u",
                       buffer[1], buffer[2], buffer[3], buffer[11],
                       static_cast<unsigned long long>(address),
                       static_cast<unsigned long long>(device_address), queue_input[12]);
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("guest-present: failed: %s", exception.what());
        return -5;
    }
}

extern "C" uint32_t d3_gpu_nv_channel_create(void) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!g_system)
        return 0;
    try {
        for (uint32_t index = 0; index < 64; index++) {
            if (g_nv_channels[index])
                continue;
            g_nv_channels[index] = g_system->GPU().AllocateChannel();
            if (!g_nv_channels[index])
                return 0;
            RendererReport("nv-channel: allocated %u bind=%d", index + 1, g_nv_channels[index]->bind_id);
            return index + 1;
        }
    } catch (const std::exception& exception) {
        RendererReport("nv-channel: allocation failed: %s", exception.what());
    }
    return 0;
}

extern "C" uint32_t d3_gpu_nv_channel_bind(uint32_t channel, uint32_t space) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!channel || channel > 64 || !g_nv_channels[channel - 1] ||
        !space || space > 64 || !g_nv_spaces[space - 1])
        return 11;
    auto& state = *g_nv_channels[channel - 1];
    if (state.initialized || state.memory_manager)
        return 8;
    state.memory_manager = g_nv_spaces[space - 1].get();
    RendererReport("nv-channel: bound %u to space=%u", channel, space);
    return 0;
}

extern "C" uint32_t d3_gpu_nv_channel_init(uint32_t channel) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!channel || channel > 64 || !g_nv_channels[channel - 1])
        return 11;
    auto& state = *g_nv_channels[channel - 1];
    if (!state.memory_manager)
        return 8;
    if (state.initialized)
        return 13;
    try {
        g_system->GPU().InitChannel(state, 0x01001b300b9be000ULL);
        RendererReport("nv-channel: initialized %u bind=%d", channel, state.bind_id);
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("nv-channel: initialization failed: %s", exception.what());
        return 8;
    }
}

extern "C" void d3_gpu_nv_channel_close(uint32_t channel) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!channel || channel > 64 || !g_nv_channels[channel - 1])
        return;
    RendererReport("nv-channel: closed %u (GPU retirement deferred to process teardown)", channel);
    g_nv_channels[channel - 1].reset();
}

extern "C" uint32_t d3_gpu_nv_submit(uint32_t channel, const uint64_t* entries, uint32_t count,
                                     uint32_t flags, uint32_t wait_id, uint32_t wait_value,
                                     uint32_t signal_id) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!channel || channel > 64 || !g_nv_channels[channel - 1] || !count || count > 4096)
        return 11;
    auto& state = *g_nv_channels[channel - 1];
    if (!state.initialized || !state.memory_manager)
        return 8;
    if ((flags & ~0x117u) || ((flags & 1u) && ((flags & 0x100u) || wait_id >= 192)) || signal_id >= 192)
        return 4;
    try {
        Tegra::CommandList commands(count);
        for (uint32_t index = 0; index < count; index++) {
            commands.command_lists[index].raw = entries[index];
            const uint64_t address = commands.command_lists[index].addr.Value();
            const uint64_t size = commands.command_lists[index].size.Value() * 4;
            bool mapped = false;
            for (const auto& mapping : g_nv_mappings) {
                if (g_nv_spaces[mapping.first.first - 1].get() == state.memory_manager &&
                    address >= mapping.first.second && address - mapping.first.second <= mapping.second.second &&
                    size <= mapping.second.second - (address - mapping.first.second))
                    mapped = true;
            }
            if (!size || !mapped)
                return 9;
        }
        d3_gpu_notify_cpu_submission();
        if (flags & 1u) {
            Tegra::Engines::Puller::FenceAction action{};
            action.op.Assign(Tegra::Engines::Puller::FenceOperation::Acquire);
            action.syncpoint_id.Assign(wait_id);
            boost::container::small_vector<Tegra::CommandHeader, 512> wait{
                Tegra::BuildCommandHeader(Tegra::BufferMethods::SyncpointPayload, 1, Tegra::SubmissionMode::Increasing),
                {wait_value},
                Tegra::BuildCommandHeader(Tegra::BufferMethods::SyncpointOperation, 1, Tegra::SubmissionMode::Increasing),
                {action.raw}};
            g_system->GPU().PushGPUEntries(state.bind_id, Tegra::CommandList{std::move(wait)});
        }
        static uint64_t submits;
        const bool report = ++submits <= 16 || submits % 1200 == 0;
        if (report) RendererReport("nv-submit: dispatch channel=%u bind=%d count=%u flags=%#x first=%#llx", channel,
                       state.bind_id, count, flags, (unsigned long long)entries[0]);
        g_system->GPU().PushGPUEntries(state.bind_id, std::move(commands));
        if (flags & 2u) {
            boost::container::small_vector<Tegra::CommandHeader, 512> signal;
            if (!(flags & 0x10u)) {
                signal.push_back(Tegra::BuildCommandHeader(Tegra::BufferMethods::WaitForIdle, 1, Tegra::SubmissionMode::Increasing));
                signal.push_back({0});
            }
            signal.push_back(Tegra::BuildCommandHeader(Tegra::BufferMethods::SyncpointPayload, 1, Tegra::SubmissionMode::Increasing));
            signal.push_back({0});
            Tegra::Engines::Puller::FenceAction action{};
            action.op.Assign(Tegra::Engines::Puller::FenceOperation::Increment);
            action.syncpoint_id.Assign(signal_id);
            for (uint32_t index = 0; index < 2; index++) {
                signal.push_back(Tegra::BuildCommandHeader(Tegra::BufferMethods::SyncpointOperation, 1, Tegra::SubmissionMode::Increasing));
                signal.push_back({action.raw});
            }
            g_system->GPU().PushGPUEntries(state.bind_id, Tegra::CommandList{std::move(signal)});
        }
        auto& syncpoints = g_system->Host1x().GetSyncpointManager();
        if (report) RendererReport("nv-submit: submitted channel=%u count=%u syncpoint=%u guest=%u host=%u", channel,
                       count, signal_id, syncpoints.GetGuestSyncpointValue(signal_id),
                       syncpoints.GetHostSyncpointValue(signal_id));
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("nv-submit: failed: %s", exception.what());
        return 8;
    }
}

extern "C" uint32_t d3_gpu_nv_as_create(uint32_t big_page) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!g_system)
        return 0;
    for (uint32_t index = 0; index < 64; index++) {
        if (g_nv_spaces[index])
            continue;
        auto space = std::make_unique<Tegra::MemoryManager>(*g_system, 37, 1ULL << 34,
                                                           big_page == 0x10000 ? 16 : 17, 12);
        g_system->GPU().InitAddressSpace(*space);
        g_nv_spaces[index] = std::move(space);
        return index + 1;
    }
    return 0;
}

extern "C" void d3_gpu_nv_diagnostics(void) {
    if (!g_system)
        return;
    auto& syncpoints = g_system->Host1x().GetSyncpointManager();
    for (uint32_t index = 1; index < 192; index++) {
        const uint32_t guest = syncpoints.GetGuestSyncpointValue(index);
        const uint32_t host = syncpoints.GetHostSyncpointValue(index);
        if (guest || host)
            RendererReport("nv-syncpoint: id=%u guest=%u host=%u", index, guest, host);
    }
}

extern "C" uint32_t d3_gpu_nv_map(uint32_t space, uint64_t gpu_address, uint64_t cpu_address,
                                  uint64_t size, uint32_t kind) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!space || space > 64 || !g_nv_spaces[space - 1])
        return 11;
    const auto backing = reinterpret_cast<uint64_t>(g_system->DeviceMemory().buffer.BackingBasePointer());
    auto* physical = g_system->ApplicationMemory().GetPointer<u8>(Common::ProcessAddress(cpu_address));
    const uint64_t physical_address = reinterpret_cast<uint64_t>(physical);
    if (physical_address < backing || physical_address - backing >= (8ULL << 30) ||
        size > (8ULL << 30) - (physical_address - backing))
        return 9;
    const DAddr address = AcquireDeviceMapping(cpu_address, size);
    if (!address)
        return 6;
    g_nv_spaces[space - 1]->Map(gpu_address, address, size, static_cast<Tegra::PTEKind>(kind), false);
    if (g_nv_spaces[space - 1]->GetPointer(gpu_address) != physical) {
        g_nv_spaces[space - 1]->Unmap(gpu_address, size);
        ReleaseDeviceMapping(address);
        return 9;
    }
    g_nv_mappings[{space, gpu_address}] = {address, size};
    RendererReport("nv-map: space=%u gpu=%#llx cpu=%#llx size=%#llx", space,
                   (unsigned long long)gpu_address, (unsigned long long)cpu_address,
                   (unsigned long long)size);
    return 0;
}

extern "C" uint32_t d3_gpu_nv_unmap(uint32_t space, uint64_t gpu_address, uint64_t size) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    const auto mapping = g_nv_mappings.find({space, gpu_address});
    if (mapping == g_nv_mappings.end() || mapping->second.second != size)
        return 11;
    g_nv_spaces[space - 1]->Unmap(gpu_address, size);
    ReleaseDeviceMapping(mapping->second.first);
    g_nv_mappings.erase(mapping);
    return 0;
}

extern "C" uint32_t d3_gpu_nv_rekind(uint32_t space, uint64_t gpu_address, uint64_t offset,
                                     uint64_t size, uint32_t kind) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!space || space > 64 || !g_nv_spaces[space - 1])
        return 11;
    const auto mapping = g_nv_mappings.find({space, gpu_address});
    if (mapping == g_nv_mappings.end() || offset > mapping->second.second ||
        size > mapping->second.second - offset)
        return 11;
    try {
        g_nv_spaces[space - 1]->Map(gpu_address + offset, mapping->second.first + offset,
                                  size, static_cast<Tegra::PTEKind>(kind), false);
        RendererReport("nv-rekind: space=%u gpu=%#llx offset=%#llx size=%#llx kind=%#x", space,
                       (unsigned long long)gpu_address, (unsigned long long)offset,
                       (unsigned long long)size, kind);
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("nv-rekind: failed: %s", exception.what());
        return 8;
    }
}

extern "C" void d3_gpu_nv_as_close(uint32_t space) {
    std::scoped_lock lock(g_nv_bridge_mutex);
    if (!space || space > 64)
        return;
    for (auto& channel : g_nv_channels) {
        if (!channel || channel->memory_manager != g_nv_spaces[space - 1].get())
            continue;
        channel.reset();
    }
    for (auto mapping = g_nv_mappings.begin(); mapping != g_nv_mappings.end();) {
        if (mapping->first.first != space) {
            ++mapping;
            continue;
        }
        ReleaseDeviceMapping(mapping->second.first);
        mapping = g_nv_mappings.erase(mapping);
    }
    g_retired_nv_spaces.push_back(std::move(g_nv_spaces[space - 1]));
}

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
    std::scoped_lock present_lock(g_present_mutex);
    if (g_window) {
        g_system->GPU().WaitForComposite();
        g_window->SetSurface(static_cast<ANativeWindow*>(native_window));
        g_surface_changed.notify_all();
        RendererReport("renderer: Android surface updated (%s)", native_window ? "visible" : "suspended");
        return 0;
    }
    if (!native_window) {
        RendererReport("renderer: no window");
        return -1;
    }

    try {
        D3::ApplyGraphicsConfiguration();
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
    const char* requested = std::getenv("D3_GPU_BACKEND");
    const D3GpuBackendRequest backend = d3_gpu_backend_request(requested);
    if (backend != D3_GPU_BACKEND_EDEN) {
        RendererReport("gpu-backend: requested=%s unavailable; linked=eden-maxwell-vulkan; refusing silent fallback",
                       requested ? requested : "");
        return -95;
    }
    RendererReport("gpu-backend: selected=eden-maxwell-vulkan");
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
            // The GMMU asserts unless the device address range was allocated first.
            gmmu.AllocateFixed(kGpuAddress, 4096);
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
            gmmu.AllocateFixed(kGpuFramebuffer, kStride * kHeight);
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

        // Two submissions: PresentManager records the frame push through the
        // scheduler, so the callback only runs on the *next* flush.  A single
        // composite would therefore never reach the present thread.
        for (int i = 0; i < 2; ++i) {
            std::vector<Tegra::FramebufferConfig> layers;
            layers.push_back(framebuffer);
            g_system->GPU().RequestComposite(std::move(layers), {});
        }
        const auto& layout = g_window->GetFramebufferLayout();
        RendererReport("composite: %ux%u framebuffer submitted (gpu=%#llx) layout=%ux%u", kWidth, kHeight,
                       (unsigned long long)kGpuFramebuffer, layout.width, layout.height);
        return 0;
    } catch (const std::exception& exception) {
        RendererReport("composite: failed: %s", exception.what());
        return -2;
    }
}