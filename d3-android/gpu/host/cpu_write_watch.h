#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace D3 {

// Only host-owned, originally RW guest mappings may be watched. The GPU's
// separate backing alias remains writable. Unknown mappings retain the exact
// snapshot fallback. Flags never move or disappear while a signal can use them.
class CpuWriteWatch {
    static constexpr std::size_t PageSize = 4096;
    static constexpr unsigned Allowed = 1, Active = 2, Dirty = 4, Busy = 8, Retired = 16;
    using Flag = std::atomic<unsigned char>;
    static_assert(Flag::is_always_lock_free);
    struct Range {
        std::atomic<std::uintptr_t> base{};
        std::size_t size{};
        std::unique_ptr<Flag[]> flags;
    };
    std::array<Range, 2> ranges;
    std::mutex scan_mutex;
    std::atomic<std::uint64_t> fault_count{};

    Flag* Find(std::uintptr_t address) const {
        for (const auto& range : ranges) {
            const auto base = range.base.load(std::memory_order_acquire);
            if (base && address >= base && address - base < range.size)
                return &range.flags[(address - base) / PageSize];
        }
        return nullptr;
    }
    static unsigned Lock(Flag& flag) {
        auto state = flag.load(std::memory_order_relaxed);
        for (;;) {
            if (state & Busy) { state = flag.load(std::memory_order_acquire); continue; }
            if (flag.compare_exchange_weak(state, state | Busy, std::memory_order_acquire,
                                           std::memory_order_relaxed)) return state;
        }
    }
    static bool Protect(std::uintptr_t address, int permission) {
        return syscall(SYS_mprotect, reinterpret_cast<void*>(address & ~(PageSize - 1)),
                       PageSize, permission) == 0;
    }
    template <typename Callback>
    void ForRange(std::uintptr_t address, std::size_t size, Callback&& callback) {
        if (!size || size > UINTPTR_MAX - address) return;
        for (auto& range : ranges) {
            const auto base = range.base.load(std::memory_order_acquire);
            if (!base || address >= base + range.size || address + size <= base) continue;
            const auto begin = address > base ? (address - base) / PageSize : 0;
            const auto end = address + size < base + range.size ?
                (address + size - base + PageSize - 1) / PageSize : range.size / PageSize;
            for (auto index = begin; index < end; ++index)
                callback(base + index * PageSize, range.flags[index]);
        }
    }
public:
    bool AddRange(std::uintptr_t base, std::size_t size) {
        std::lock_guard lock(scan_mutex);
        if (sysconf(_SC_PAGESIZE) != PageSize || !base || !size ||
            ((base | size) & (PageSize - 1)) || size > UINTPTR_MAX - base) return false;
        for (auto& range : ranges) {
            if (range.base.load() == base) return range.size == size;
            if (range.base.load()) continue;
            range.flags = std::make_unique<Flag[]>(size / PageSize);
            range.size = size;
            range.base.store(base, std::memory_order_release);
            return true;
        }
        return false;
    }
    // Call before removing/changing a mapping, and after granting RW access.
    void SetAllowed(std::uintptr_t address, std::size_t size, bool allowed) {
        std::lock_guard lock(scan_mutex);
        ForRange(address, size, [&](auto page, Flag& flag) {
            const auto state = Lock(flag);
            if (state & Active) Protect(page, PROT_READ | PROT_WRITE);
            flag.store(allowed ? Allowed | ((state & (Active | Retired)) ? Retired : 0) : 0,
                       std::memory_order_release);
        });
    }
    // Gather holds this across both worker scans. Kernel writes hold the same
    // lock until the syscall finishes, so rearming cannot cause a short read or
    // EFAULT halfway through an otherwise valid IPC/file output buffer.
    std::unique_lock<std::mutex> LockScan() { return std::unique_lock(scan_mutex); }
    void BeginKernelWrite(std::uintptr_t address, std::size_t size) {
        scan_mutex.lock();
        ForRange(address, size, [&](auto page, Flag& flag) {
            auto state = Lock(flag);
            if (state & Active) {
                Protect(page, PROT_READ | PROT_WRITE);
                state |= Dirty;
            }
            flag.store(state, std::memory_order_release);
        });
    }
    void EndKernelWrite() { scan_mutex.unlock(); }
    bool IsWritable(std::uintptr_t address) const {
        const auto* flag = Find(address);
        return flag && (flag->load(std::memory_order_acquire) & Allowed);
    }
    void Untrack(std::uintptr_t address) {
        std::lock_guard lock(scan_mutex);
        UntrackUnderScan(address);
    }
    void UntrackUnderScan(std::uintptr_t address) {
        if (auto* flag = Find(address)) {
            const auto state = Lock(*flag);
            if (state & Active) Protect(address, PROT_READ | PROT_WRITE);
            flag->store((state & Allowed) | ((state & (Active | Retired)) ? Retired : 0),
                        std::memory_order_release);
        }
    }
    // The caller compares the snapshot after arming, so writes between the
    // previous snapshot and the protection syscall cannot be lost.
    bool IsClean(std::uintptr_t address) {
        auto* flag = Find(address);
        if (!flag) return false;
        const auto initial = flag->load(std::memory_order_acquire);
        if (!(initial & Busy) && (initial & (Allowed | Active | Dirty)) == (Allowed | Active))
            return true;
        const auto state = Lock(*flag);
        bool clean = false;
        unsigned next = state;
        if (state & Allowed) {
            clean = (state & Active) && !(state & Dirty);
            if (!clean) {
                if (Protect(address, PROT_READ)) next = Allowed | Active;
                else next = 0; // Keep scanning exactly if the mapping cannot be armed.
            }
        }
        flag->store(next, std::memory_order_release);
        return clean;
    }
    std::uint64_t FaultCount() const { return fault_count.load(std::memory_order_relaxed); }
    // Some Android kernels report MAPERR for a protected data page. Active
    // metadata and the caller's ESR write check identify our faults. No allocations, libc
    // locks, logging, TLS or callbacks are allowed on this signal path.
    bool HandleFault(std::uintptr_t address) {
        auto* flag = Find(address);
        if (!flag) return false;
        const auto initial = flag->load(std::memory_order_acquire);
        if (!(initial & Allowed) || !(initial & (Active | Retired)))
            return false;
        auto state = Lock(*flag);
        if (!(state & Allowed) || !(state & (Active | Retired))) {
            flag->store(state, std::memory_order_release); return false;
        }
        // An eviction can restore RW while a previously raised fault is pending.
        const bool handled = !(state & Active) || Protect(address, PROT_READ | PROT_WRITE);
        if (handled && (state & Active)) state |= Dirty;
        flag->store(state, std::memory_order_release);
        if (handled) fault_count.fetch_add(1, std::memory_order_relaxed);
        return handled;
    }
};

} // namespace D3
