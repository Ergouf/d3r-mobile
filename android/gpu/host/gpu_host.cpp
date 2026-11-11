// Host side of the Eden GPU port.
//
// Eden's video_core is written against a small set of Core:: / Common:: entry
// points.  This file provides the ones the Vulkan path actually reaches, on top
// of the d3 guest memory that d3_host.c owns.  Everything here is deliberately
// thin: the GPU service must not depend on Eden's kernel, services or config
// layer.
#include <android/log.h>
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>

#include <chrono>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <memory>
#include <map>
#include <mutex>
#include <string>
#include <system_error>
#include <vector>

#include "android/app/src/main/jni/android_settings.h"
#include "common/assert.h"
#include "common/common_types.h"
#include "common/fs/fs.h"
#include "common/fs/path_util.h"
#include "common/logging.h"
#include "common/settings.h"
#include "common/thread.h"
#include "core/core.h"
#include "core/core_timing.h"
#include "core/device_memory.h"
#include "core/memory.h"
#include "core/perf_stats.h"
#include "video_core/gpu.h"
#include "video_core/host1x/host1x.h"
#include "cpu_write_tracker.h"
#include "gpu_bridge.h"

// Settings::values lives in Eden's common/settings.cpp, which the archive also
// compiles; only the Android-side table is host-owned.

namespace AndroidSettings {
Values values;
} // namespace AndroidSettings

namespace {

// Guest RAM is owned by the host translation layer; the GPU maps GPU virtual
// addresses through Eden's page tables onto this range.
u8* g_guest_base = nullptr;
std::size_t g_guest_size = 0;
bool g_powered_on = true;

constexpr std::size_t kDefaultBackingSize = 8ULL << 30;
constexpr std::size_t kDefaultVirtualSize = 64ULL << 30;
struct AliasBacking {
    uint64_t size;
    uint64_t physical;
};
std::mutex g_alias_mutex;
std::map<uint64_t, AliasBacking> g_alias_backings;
uint64_t g_alias_physical = 4ULL << 30;
std::atomic<bool> g_cache_scan_enabled{true};
std::atomic<uint64_t> g_cache_generation{1};
D3::CpuWriteTracker g_cpu_write_tracker;
D3::CpuWriteWatch g_cpu_write_watch;
bool g_write_watch_enabled = false;
std::atomic<bool> g_force_cache_scan{};

std::size_t EnvSize(const char* name, std::size_t default_bytes) {
    const char* value = std::getenv(name);
    if (!value || !*value) {
        return default_bytes;
    }
    const unsigned long long mib = std::strtoull(value, nullptr, 10);
    return mib ? static_cast<std::size_t>(mib) << 20 : default_bytes;
}

} // namespace

extern "C" __attribute__((visibility("default"))) void d3_gpu_set_guest_memory(void* base, std::size_t size) {
    g_guest_base = static_cast<u8*>(base);
    g_guest_size = size;
}

extern "C" __attribute__((visibility("default"))) void d3_gpu_set_powered_on(bool on) {
    g_powered_on = on;
}

// Bring-up probe: constructs the GPU host state (which allocates the sparse
// device memory backing) and reports it in logcat.  d3_jni.c calls this before
// the guest starts so a device log proves the C++ runtime and the archive are
// live inside libd3host.so.
extern "C" int d3_vk_probe(void* native_window);
extern "C" __attribute__((visibility("default"))) void d3_gpu_probe_init(void) {
    static Core::System system;
    auto& memory = system.DeviceMemory();
    __android_log_print(ANDROID_LOG_INFO, "d3gpu",
                        "probe: device memory backing=%p virtual=%p", (void*)memory.buffer.BackingBasePointer(),
                        (void*)memory.buffer.VirtualBasePointer());

    // Vulkan bring-up runs headless for now; the swapchain step passes the
    // ANativeWindow from the Java SurfaceView instead of nullptr.
    d3_vk_probe(nullptr);
}

extern "C" void* d3_gpu_guest_heap(uint64_t* size) {
    static Core::System system;
    *size = 3ULL << 30;
    auto* base = system.DeviceMemory().buffer.BackingBasePointer() + (64ULL << 20);
    if (mprotect(base, *size, PROT_NONE) != 0)
        return nullptr;
    g_cpu_write_watch.AddRange(reinterpret_cast<uintptr_t>(base), *size);
    if (g_write_watch_enabled) g_cpu_write_tracker.SetWriteWatch(&g_cpu_write_watch);
    __android_log_print(ANDROID_LOG_INFO, "d3gpu", "CPU write watch: %s", g_write_watch_enabled ? "enabled" : "disabled");
    return base;
}

extern "C" void* d3_gpu_guest_alias(uint64_t* size) {
    static Core::System system;
    *size = kDefaultVirtualSize;
    auto* base = system.DeviceMemory().buffer.VirtualBasePointer();
    g_cpu_write_watch.AddRange(reinterpret_cast<uintptr_t>(base), *size);
    return base;
}

extern "C" int d3_gpu_alias_commit(uint64_t address, uint64_t size, int mapped) {
    static Core::System system;
    std::scoped_lock lock(g_alias_mutex);
    auto& buffer = system.DeviceMemory().buffer;
    const auto base = reinterpret_cast<uint64_t>(buffer.VirtualBasePointer());
    if (address < base || address - base > kDefaultVirtualSize ||
        size > kDefaultVirtualSize - (address - base))
        return -1;
    if (!mapped) {
        g_cpu_write_watch.SetAllowed(address, size, false);
        buffer.Unmap(address - base, size, false);
        auto found = g_alias_backings.upper_bound(address);
        if (found != g_alias_backings.begin())
            --found;
        while (found != g_alias_backings.end() && found->first < address + size) {
            const uint64_t start = found->first;
            const AliasBacking backing = found->second;
            if (start + backing.size <= address) {
                ++found;
                continue;
            }
            found = g_alias_backings.erase(found);
            if (start < address)
                g_alias_backings.emplace(start, AliasBacking{address - start, backing.physical});
            if (start + backing.size > address + size)
                g_alias_backings.emplace(address + size, AliasBacking{
                    start + backing.size - address - size, backing.physical + address + size - start});
        }
        return 0;
    }
    if (size > kDefaultBackingSize - g_alias_physical)
        return -1;
    uint64_t cursor = address;
    while (cursor < address + size) {
        auto next = g_alias_backings.upper_bound(cursor);
        if (next != g_alias_backings.begin()) {
            const auto previous = std::prev(next);
            if (cursor < previous->first + previous->second.size) {
                cursor = std::min(address + size, previous->first + previous->second.size);
                continue;
            }
        }
        const uint64_t end = next == g_alias_backings.end() ? address + size :
                             std::min(address + size, next->first);
        const uint64_t bytes = end - cursor;
        buffer.Map(cursor - base, g_alias_physical, bytes, Common::MemoryPermission::ReadWrite, false);
        g_cpu_write_watch.SetAllowed(cursor, bytes, true);
        g_alias_backings.emplace(cursor, AliasBacking{bytes, g_alias_physical});
        g_alias_physical += bytes;
        cursor = end;
    }
    return 0;
}

extern "C" void d3_gpu_set_cache_scan(int enabled) {
    g_cache_scan_enabled.store(enabled != 0, std::memory_order_relaxed);
    __android_log_print(ANDROID_LOG_INFO, "d3gpu", "cache-scan: enabled=%d", enabled != 0);
}

extern "C" void d3_gpu_notify_cpu_submission(void) {
    g_cache_generation.fetch_add(1, std::memory_order_release);
}

extern "C" int d3_gpu_handle_cpu_write_fault(uint64_t address) {
    return g_cpu_write_watch.HandleFault(address);
}
extern "C" void d3_gpu_set_write_watch(int enabled) { g_write_watch_enabled = enabled != 0; }
extern "C" int d3_gpu_cache_scan_mode(void) {
    return !g_write_watch_enabled ? 0 : g_force_cache_scan.load(std::memory_order_relaxed) ? 2 : 1;
}
extern "C" void d3_gpu_cpu_memory_permission(uint64_t address, uint64_t size, int writable) {
    g_cpu_write_watch.SetAllowed(address, size, writable != 0);
}
extern "C" void d3_gpu_begin_cpu_write(uint64_t address, uint64_t size) {
    g_cpu_write_watch.BeginKernelWrite(address, size);
}
extern "C" void d3_gpu_end_cpu_write(void) { g_cpu_write_watch.EndKernelWrite(); }
extern "C" int d3_gpu_cpu_memory_writable(uint64_t address) {
    return g_cpu_write_watch.IsWritable(address);
}

namespace Core {

// ---------------------------------------------------------------- DeviceMemory
DeviceMemory::DeviceMemory()
    : buffer{EnvSize("D3_GPU_BACKING_MB", kDefaultBackingSize),
             EnvSize("D3_GPU_VIRTUAL_MB", kDefaultVirtualSize)} {}
DeviceMemory::~DeviceMemory() = default;

// --------------------------------------------------------------- CoreTiming
u64 CoreTiming::GetGPUTicks() {
    using namespace std::chrono;
    static const auto start = steady_clock::now();
    return static_cast<u64>(duration_cast<nanoseconds>(steady_clock::now() - start).count());
}

// ------------------------------------------------------------------ PerfStats
void PerfStats::EndSystemFrame() {}
void PerfStats::EndGameFrame() {}

// ---------------------------------------------------------------- GuestMemory
namespace {

// The guest runs in this process (its ELF is mapped where p_vaddr says), so a
// guest virtual address is already a host pointer.  An explicit base is only
// needed if a future loader relocates the image.
inline u8* GuestPointer(u64 addr, std::size_t size) {
    {
        std::scoped_lock lock(g_alias_mutex);
        auto backing = g_alias_backings.upper_bound(addr);
        if (backing != g_alias_backings.begin()) {
            --backing;
            if (addr >= backing->first && addr - backing->first < backing->second.size &&
                size <= backing->second.size - (addr - backing->first)) {
                static Core::System system;
                return system.DeviceMemory().buffer.BackingBasePointer() + backing->second.physical +
                       (addr - backing->first);
            }
        }
    }
    if (g_guest_base) {
        if (addr > g_guest_size || size > g_guest_size - addr) {
            return nullptr;
        }
        return g_guest_base + addr;
    }
    return reinterpret_cast<u8*>(addr);
}

} // namespace

void Memory::Memory::FlushRegion(u64, std::size_t) {}
void Memory::Memory::InvalidateRegion(u64, std::size_t) {}

u8* Memory::Memory::GetSpan(u64 addr, std::size_t size) {
    return GuestPointer(addr, size);
}

const u8* Memory::Memory::GetSpan(u64 addr, std::size_t size) const {
    return GuestPointer(addr, size);
}

u8* Memory::Memory::GetPointer(Common::ProcessAddress vaddr) {
    return GuestPointer(GetInteger(vaddr), 1);
}

u8* Memory::Memory::GetPointerSilent(Common::ProcessAddress vaddr) {
    return GuestPointer(GetInteger(vaddr), 1);
}

const u8* Memory::Memory::GetPointer(Common::ProcessAddress vaddr) const {
    return GuestPointer(GetInteger(vaddr), 1);
}

void Memory::Memory::ReadBlock(u64 src, void* dest, std::size_t size) const {
    if (const u8* p = GuestPointer(src, size)) {
        std::memcpy(dest, p, size);
    } else if (dest) {
        std::memset(dest, 0, size);
    }
}

void Memory::Memory::ReadBlockUnsafe(u64 src, void* dest, std::size_t size) const {
    ReadBlock(src, dest, size);
}

void Memory::Memory::WriteBlock(u64 dest, const void* src, std::size_t size) {
    if (u8* p = GuestPointer(dest, size)) {
        g_cpu_write_watch.BeginKernelWrite(dest, size);
        std::memcpy(p, src, size);
        g_cpu_write_watch.EndKernelWrite();
    }
}

void Memory::Memory::WriteBlockCached(u64 dest, const void* src, std::size_t size) {
    WriteBlock(dest, src, size);
}

void Memory::Memory::WriteBlockUnsafe(u64 dest, const void* src, std::size_t size) {
    WriteBlock(dest, src, size);
}

void Memory::Memory::RasterizerMarkRegionCached(Common::ProcessAddress vaddr, u64 size, bool cached) {
    if (!g_cache_scan_enabled.load(std::memory_order_relaxed) || !size ||
        GetInteger(vaddr) > UINT64_MAX - size || GetInteger(vaddr) + size > UINT64_MAX - 4095u)
        return;
    const uint64_t start = GetInteger(vaddr) & ~4095ULL;
    const uint64_t end = (GetInteger(vaddr) + size + 4095u) & ~4095ULL;
    for (uint64_t page = start; page < end; page += 4096) {
        auto* pointer = GuestPointer(page, 4096);
        if (!pointer)
            continue;
        g_cpu_write_tracker.SetCached(page, pointer, cached);
    }
}

// --------------------------------------------------------------------- System
namespace {

struct HostState {
    Core::DeviceMemory device_memory{};
    Core::Memory::Memory app_memory{};
    Core::PerfStats perf{};
    Core::CoreTiming timing{};
    std::unique_ptr<Tegra::GPU> gpu{};
    std::unique_ptr<Tegra::Host1x::Host1x> host1x{};
};

HostState& State() {
    static const bool configured = [] {
        Settings::values.memory_layout_mode.SetValue(Settings::MemoryLayout::Memory_8Gb);
        return true;
    }();
    (void)configured;
    static HostState state;
    return state;
}

} // namespace

Tegra::GPU& System::GPU() {
    auto& state = State();
    if (!state.gpu) {
        state.gpu = std::make_unique<Tegra::GPU>(*this, true, false);
    }
    return *state.gpu;
}

Tegra::Host1x::Host1x& System::Host1x() {
    auto& state = State();
    if (!state.host1x) {
        state.host1x = std::make_unique<Tegra::Host1x::Host1x>(*this);
    }
    return *state.host1x;
}

CoreTiming& System::CoreTiming() {
    return State().timing;
}

Core::DeviceMemory& System::DeviceMemory() {
    return State().device_memory;
}

const Core::DeviceMemory& System::DeviceMemory() const {
    return State().device_memory;
}

Core::Memory::Memory& System::ApplicationMemory() {
    return State().app_memory;
}

const Core::Memory::Memory& System::ApplicationMemory() const {
    return State().app_memory;
}

bool System::IsPoweredOn() const {
    return g_powered_on;
}

void System::RegisterHostThread() {}

void System::GatherGPUDirtyMemory(std::function<void(PAddr, std::size_t)>& callback) {
    if (!g_cache_scan_enabled.load(std::memory_order_relaxed))
        return;
    static thread_local uint64_t scanned_generation = 0;
    const uint64_t generation = g_cache_generation.load(std::memory_order_acquire);
    if (generation == scanned_generation)
        return;
    scanned_generation = generation;
    static const bool profile_enabled = [] {
        const char* value = std::getenv("D3_FRAME_TIMINGS");
        return value && std::strcmp(value, "1") == 0;
    }();
    static const std::string full_scan_marker = [] {
        const char* path = std::getenv("D3_FULL_SCAN_FILE");
        return std::string(path ? path : "");
    }();
    static thread_local uint32_t mode_checks;
    if (profile_enabled && g_write_watch_enabled && ++mode_checks % 32 == 1) {
        const bool requested = !full_scan_marker.empty() && access(full_scan_marker.c_str(), F_OK) == 0;
        if (requested != g_force_cache_scan.load(std::memory_order_relaxed)) {
            g_cpu_write_tracker.SetForceFullScan(requested);
            g_force_cache_scan.store(requested, std::memory_order_relaxed);
        }
    }
    const int cache_mode = d3_gpu_cache_scan_mode();
    const auto started = std::chrono::steady_clock::now();
    Common::ScratchBuffer<u32> buffer;
    const auto [scanned, changed] = g_cpu_write_tracker.Gather([&](uint64_t, const u8* pointer) {
        Host1x().memory_manager.ApplyOpOnPointer(pointer, buffer, [&](DAddr address) {
            if (address)
                callback(address, 4096);
        });
    });
    const auto elapsed_us = static_cast<uint64_t>(std::chrono::duration_cast<
        std::chrono::microseconds>(std::chrono::steady_clock::now() - started).count());
    static thread_local uint64_t reports = 0;
    struct ScanBatch {
        uint64_t count{}, total_us{}, max_us{}, begin_us{}, pages{}, changed{};
        int mode{};
    };
    static thread_local ScanBatch batch;
    if (batch.count && batch.mode != cache_mode) batch = {};
    if (!batch.count) {
        batch.begin_us = static_cast<uint64_t>(std::chrono::duration_cast<
            std::chrono::microseconds>(started.time_since_epoch()).count());
        batch.mode = cache_mode;
    }
    ++batch.count;
    batch.total_us += elapsed_us;
    if (elapsed_us > batch.max_us) batch.max_us = elapsed_us;
    batch.pages += scanned;
    batch.changed += changed;
    // A 256-scan point sample always coincides with the write-watch audit.
    // Include every scan in the batch so its mean represents normal work too.
    if (reports++ < 24 || reports % 256 == 0) {
        d3_gpu_report_cache_scan(scanned, changed, elapsed_us, generation,
                                g_cpu_write_watch.FaultCount(), g_cpu_write_tracker.WatchMisses(),
                                batch.count, batch.total_us, batch.max_us, batch.begin_us,
                                batch.pages, batch.changed, batch.mode);
        batch = {};
    }
}

Core::PerfStats& System::GetPerfStats() {
    return State().perf;
}

const Core::PerfStats& System::GetPerfStats() const {
    return State().perf;
}

} // namespace Core

// ------------------------------------------------------------- Common helpers
namespace Common {

void* AllocateMemoryPages(std::size_t size) noexcept {
    void* ptr = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    return ptr == MAP_FAILED ? nullptr : ptr;
}

void FreeMemoryPages(void* ptr, std::size_t size) noexcept {
    if (ptr) {
        munmap(ptr, size);
    }
}




} // namespace Common
