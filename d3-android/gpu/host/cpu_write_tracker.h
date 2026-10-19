#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <map>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <sys/resource.h>
#include <sched.h>
#include <cstdio>
#include <utility>
#include <vector>
#include "cpu_write_watch.h"

namespace D3 {

class CpuWriteTracker {
public:
    static constexpr std::size_t PageSize = 4096;
    void SetWriteWatch(CpuWriteWatch* value) { watch = value; }
    std::size_t WatchMisses() const { return watch_misses.load(std::memory_order_relaxed); }
    ~CpuWriteTracker() {
        { std::lock_guard lock(work_mutex); stopping = true; }
        work_ready.notify_all();
        for (auto& worker : workers) if (worker.joinable()) worker.join();
    }

    void SetCached(std::uint64_t address, const std::uint8_t* pointer, bool cached) {
        std::scoped_lock lock(mutex);
        const auto found = indices.find(address);
        if (!cached) {
            if (found != indices.end()) {
                if (watch) watch->Untrack(address);
                const std::size_t index = found->second;
                if (index + 1 != pages.size()) {
                    pages[index] = std::move(pages.back());
                    indices[pages[index].address] = index;
                }
                pages.pop_back();
                indices.erase(found);
            }
            return;
        }
        if (!pointer || found != indices.end())
            return;
        Page page{};
        page.address = address;
        page.pointer = pointer;
        std::memcpy(page.snapshot.data(), pointer, PageSize);
        indices.emplace(address, pages.size());
        pages.push_back(std::move(page));
    }

    template <typename Callback>
    std::pair<std::size_t, std::size_t> Gather(Callback&& callback) {
        std::vector<std::pair<std::uint64_t, const std::uint8_t*>> dirty;
        std::size_t scanned;
        {
            std::scoped_lock lock(mutex);
            auto watch_lock = watch ? watch->LockScan() : std::unique_lock<std::mutex>{};
            scanned = pages.size();
            audit_watch = (++scan_count % 256) == 0;
            if (pages.size() < 2048) {
                Scan(0, pages.size(), dirty);
            } else {
                if (!workers[0].joinable()) {
                    for (std::size_t i = 0; i < workers.size(); i++)
                        workers[i] = std::thread([this, i] { Worker(i); });
                }
                for (auto& part : work_dirty) part.clear();
                {
                    std::lock_guard work_lock(work_mutex);
                    work_size = pages.size(); completed = 0; ++generation;
                }
                work_ready.notify_all();
                Scan(0, pages.size() / 3, dirty);
                std::unique_lock work_lock(work_mutex);
                work_done.wait(work_lock, [&] { return completed == workers.size(); });
                for (const auto& part : work_dirty) dirty.insert(dirty.end(), part.begin(), part.end());
            }
        }
        for (const auto& [address, pointer] : dirty)
            callback(address, pointer);
        return {scanned, dirty.size()};
    }

private:
    struct Page {
        std::uint64_t address;
        const std::uint8_t* pointer;
        unsigned quiet_scans{};
        std::array<std::uint8_t, PageSize> snapshot;
    };

    std::mutex mutex;
    CpuWriteWatch* watch{};
    std::size_t scan_count{};
    bool audit_watch{};
    std::atomic<std::size_t> watch_misses{};
    // Stream snapshots in one contiguous allocation on each submission. A map
    // node per 4 KiB snapshot defeated hardware prefetch during the full scan.
    std::map<std::uint64_t, std::size_t> indices;
    std::vector<Page> pages;
    using Dirty = std::vector<std::pair<std::uint64_t, const std::uint8_t*>>;
    void Scan(std::size_t begin, std::size_t end, Dirty& dirty) {
        for (std::size_t i = begin; i < end; i++) {
            auto& page = pages[i];
            // Keep frequently written allocations writable. Watching a texture
            // after sixteen unchanged scans removes its memory-bandwidth cost
            // without faulting on every update of a dynamic uniform/vertex page.
            const bool clean = watch && page.quiet_scans >= 16 && watch->IsClean(page.address);
            if (clean && !audit_watch) continue;
            if (std::memcmp(page.snapshot.data(), page.pointer, PageSize) == 0) {
                if (page.quiet_scans < 16) ++page.quiet_scans;
                continue;
            }
            if (clean && watch->IsClean(page.address)) watch_misses.fetch_add(1, std::memory_order_relaxed);
            page.quiet_scans = 0;
            if (watch) watch->UntrackUnderScan(page.address);
            std::memcpy(page.snapshot.data(), page.pointer, PageSize);
            dirty.emplace_back(page.address, page.pointer);
        }
    }
    void Worker(std::size_t index) {
        setpriority(PRIO_PROCESS, 0, -8);
        cpu_set_t allowed;
        if (sched_getaffinity(0, sizeof allowed, &allowed) == 0) {
            std::vector<int> performance;
            for (int cpu = 0; cpu < CPU_SETSIZE; cpu++) {
                if (!CPU_ISSET(cpu, &allowed)) continue;
                char path[128]; std::snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/cpu_capacity", cpu);
                FILE* file = std::fopen(path, "r");
                int capacity = 0;
                if (file) { (void)std::fscanf(file, "%d", &capacity); std::fclose(file); }
                if (capacity >= 700) performance.push_back(cpu);
            }
            if (performance.size() >= 3) {
                cpu_set_t selected; CPU_ZERO(&selected); CPU_SET(performance[index], &selected);
                (void)sched_setaffinity(0, sizeof selected, &selected);
            }
        }
        std::size_t observed = 0;
        std::unique_lock lock(work_mutex);
        for (;;) {
            work_ready.wait(lock, [&] { return stopping || generation != observed; });
            if (stopping) return;
            observed = generation;
            const auto size = work_size;
            lock.unlock();
            Scan(size * (index + 1) / 3, size * (index + 2) / 3, work_dirty[index]);
            lock.lock();
            ++completed; work_done.notify_one();
        }
    }
    std::mutex work_mutex;
    std::condition_variable work_ready, work_done;
    std::array<std::thread, 2> workers;
    std::array<Dirty, 2> work_dirty;
    std::size_t generation{}, completed{}, work_size{};
    bool stopping{};
};

}
