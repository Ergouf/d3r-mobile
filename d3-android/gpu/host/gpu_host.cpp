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
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <memory>
#include <string>
#include <system_error>

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

constexpr std::size_t kDeviceBackingSize = 4ULL << 30; // physical DRAM window
constexpr std::size_t kDeviceVirtualSize = 8ULL << 30; // sparse reserve

} // namespace

extern "C" void d3_gpu_set_guest_memory(void* base, std::size_t size) {
    g_guest_base = static_cast<u8*>(base);
    g_guest_size = size;
}

extern "C" void d3_gpu_set_powered_on(bool on) {
    g_powered_on = on;
}

namespace Core {

// ---------------------------------------------------------------- DeviceMemory
DeviceMemory::DeviceMemory() : buffer{kDeviceBackingSize, kDeviceVirtualSize} {}
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

inline u8* GuestPointer(u64 addr, std::size_t size) {
    if (!g_guest_base || addr > g_guest_size || size > g_guest_size - addr) {
        return nullptr;
    }
    return g_guest_base + addr;
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
        std::memcpy(p, src, size);
    }
}

void Memory::Memory::WriteBlockCached(u64 dest, const void* src, std::size_t size) {
    WriteBlock(dest, src, size);
}

void Memory::Memory::WriteBlockUnsafe(u64 dest, const void* src, std::size_t size) {
    WriteBlock(dest, src, size);
}

void Memory::Memory::RasterizerMarkRegionCached(Common::ProcessAddress, u64, bool) {}

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
    static HostState state;
    return state;
}

} // namespace

Tegra::GPU& System::GPU() {
    auto& state = State();
    if (!state.gpu) {
        state.gpu = std::make_unique<Tegra::GPU>(*this, false, false);
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

void System::GatherGPUDirtyMemory(std::function<void(PAddr, std::size_t)>&) {}

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

namespace Log {

void FmtLogMessageImpl(Class log_class, Level log_level, const char* filename,
                       unsigned int line_num, const char* function,
                       fmt::string_view format, const fmt::format_args& args) {
    static constexpr int kPriority[] = {
        ANDROID_LOG_VERBOSE, ANDROID_LOG_DEBUG, ANDROID_LOG_INFO,
        ANDROID_LOG_WARN, ANDROID_LOG_ERROR, ANDROID_LOG_FATAL,
    };
    const int priority = kPriority[static_cast<int>(log_level)];
    const std::string message = fmt::vformat(format, args);
    __android_log_print(priority, "d3gpu", "%s:%u %s: %s", filename, line_num, function,
                        message.c_str());
}

} // namespace Log

namespace FS {

bool Exists(const std::filesystem::path& path) {
    std::error_code ec;
    return std::filesystem::exists(path, ec);
}

bool CreateDir(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::create_directory(path, ec);
    return !ec;
}

bool CreateDirs(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::create_directories(path, ec);
    return !ec;
}

bool RemoveFile(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::remove(path, ec);
    return !ec;
}

bool RenameFile(const std::filesystem::path& old_path, const std::filesystem::path& new_path) {
    std::error_code ec;
    std::filesystem::rename(old_path, new_path, ec);
    return !ec;
}


const std::filesystem::path& GetEdenPath(EdenPath eden_path) {
    static std::filesystem::path root = [] {
        const char* env = std::getenv("D3_EDEN_DIR");
        return std::filesystem::path{env ? env : "/data/local/tmp/d3/eden"};
    }();
    static std::filesystem::path cache;
    switch (eden_path) {
    case EdenPath::ShaderDir:
        cache = root / "shader";
        break;
    case EdenPath::CacheDir:
        cache = root / "cache";
        break;
    default:
        cache = root;
        break;
    }
    return cache;
}

} // namespace FS

} // namespace Common
