#include "../gpu/host/cpu_write_tracker.h"

#include <cstdio>
#include <csignal>
#include <cerrno>
#include <fcntl.h>
#include <sys/uio.h>

static D3::CpuWriteWatch* signal_watch;
static volatile sig_atomic_t faults;
static void write_fault(int signal, siginfo_t* info, void*) {
    if (signal == SIGSEGV && (info->si_code == SEGV_ACCERR || info->si_code == SEGV_MAPERR) && signal_watch &&
        signal_watch->HandleFault(reinterpret_cast<std::uintptr_t>(info->si_addr))) {
        __atomic_fetch_add(&faults, 1, __ATOMIC_RELAXED);
        return;
    }
    dprintf(2, "unexpected signal=%d code=%d address=%p writable=%d\n", signal, info->si_code, info->si_addr,
        signal_watch && signal_watch->IsWritable(reinterpret_cast<std::uintptr_t>(info->si_addr)));
    _exit(99);
}

#define CHECK(condition) do { if (!(condition)) { \
    std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

int main() {
    setbuf(stdout, nullptr);
    D3::CpuWriteTracker tracker;
    std::array<std::uint8_t, D3::CpuWriteTracker::PageSize * 2> memory{};
    tracker.SetCached(0x1000, memory.data(), true);
    tracker.SetCached(0x2000, memory.data() + 4096, true);
    std::vector<std::uint64_t> addresses;
    auto gather = [&] {
        addresses.clear();
        return tracker.Gather([&](std::uint64_t address, const std::uint8_t* pointer) {
            if (pointer == memory.data() + address - 0x1000)
                addresses.push_back(address);
        });
    };
    CHECK(gather().second == 0);
    memory[7] = 0x81;
    tracker.SetCached(0x1000, memory.data(), true);
    CHECK(gather().second == 1 && addresses == std::vector<std::uint64_t>{0x1000});
    CHECK(gather().second == 0);
    memory[4095] = 0x22;
    memory[4096] = 0x33;
    CHECK(gather().second == 2 && addresses.size() == 2);
    tracker.SetCached(0x1000, memory.data(), false);
    memory[3] = 0x44;
    CHECK(gather().second == 0);
    tracker.SetCached(0x1000, memory.data(), true);
    CHECK(gather().second == 0);
    memory[8191] = 0x55;
    std::size_t callbacks = 0;
    const auto result = tracker.Gather([&](std::uint64_t address, const std::uint8_t* pointer) {
        tracker.SetCached(address, pointer, false);
        callbacks++;
    });
    CHECK(result.second == 1 && callbacks == 1 && gather().first == 1);
    tracker.SetCached(0x3000, nullptr, true);
    CHECK(gather().first == 1);
    std::vector<std::uint8_t> large(4096 * 4096);
    for (std::size_t i = 0; i < 4096; i++) tracker.SetCached(0x1000000 + i * 4096, large.data() + i * 4096, true);
    CHECK(gather().second == 0);
    for (std::size_t i = 0; i < 4096; i += 31) large[i * 4096 + i % 4096] = 1;
    callbacks = 0;
    const auto parallel = tracker.Gather([&](std::uint64_t address, const std::uint8_t* pointer) {
        tracker.SetCached(address, pointer, false); callbacks++;
    });
    CHECK(parallel.first == 4097 && parallel.second == 133 && callbacks == 133);
    CHECK(gather().second == 0);
    std::puts("PASS: CPU cache page snapshots, exact changes, repeat-cache, boundaries, uncache and reentrant collection");

    D3::CpuWriteWatch watch;
    signal_watch = &watch;
    struct sigaction action{}; action.sa_sigaction = write_fault; action.sa_flags = SA_SIGINFO;
    CHECK(sigaction(SIGSEGV, &action, nullptr) == 0);
    constexpr std::size_t bytes = 4096 * 4096;
    auto* watched = static_cast<std::uint8_t*>(mmap(nullptr, bytes, PROT_READ | PROT_WRITE,
                                                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    CHECK(watched != MAP_FAILED);
    auto base = reinterpret_cast<std::uintptr_t>(watched);
    std::printf("watch base=%p size=%zu\n", watched, bytes);
    CHECK(watch.AddRange(base, bytes));
    watch.SetAllowed(base, bytes, true);
    D3::CpuWriteTracker tracked;
    tracked.SetWriteWatch(&watch);
    for (std::size_t i = 0; i < bytes; i += 4096) tracked.SetCached(base + i, watched + i, true);
    auto collect = [&] { return tracked.Gather([](auto, auto) {}); };
    for (unsigned n = 0; n < 17; ++n) CHECK(collect().second == 0);
    CHECK(collect().second == 0 && collect().second == 0);
    std::puts("watch armed");
    watched[7] = 8;
    watched[4095] = 9;
    watched[4096] = 10;
    CHECK(faults == 2 && collect().second == 2 && collect().second == 0);
    for (unsigned n = 0; n < 17; ++n) CHECK(collect().second == 0);
    // Same-value stores cause a fault, but not a false GPU invalidation.
    *static_cast<volatile std::uint8_t*>(watched + 7) = 8;
    CHECK(faults == 3 && collect().second == 0);
    // Kernel copies must be bracketed; the watch lock excludes rearming until done.
    std::array<std::uint8_t, 8192> output{}; output.fill(0x57);
    iovec source{output.data(), output.size()}, destination{watched + 2, output.size()};
    CHECK(process_vm_writev(getpid(), &source, 1, &destination, 1, 0) == -1 && errno == EFAULT);
    watch.BeginKernelWrite(base + 2, output.size());
    CHECK(process_vm_writev(getpid(), &source, 1, &destination, 1, 0) == output.size());
    watch.EndKernelWrite();
    CHECK(collect().second == 3 && collect().second == 0);
    // Race writers against repeated parallel scans, then verify the final value.
    std::atomic<bool> finished{};
    std::thread writer([&] {
        for (unsigned n = 1; n <= 10000; ++n) {
            auto* word = reinterpret_cast<volatile unsigned*>(watched + (n % 1024) * 4096);
            *word = n;
        }
        finished.store(true, std::memory_order_release);
    });
    while (!finished.load(std::memory_order_acquire)) collect();
    writer.join();
    collect(); CHECK(collect().second == 0);
    for (unsigned n = 0; n < 1024; ++n) {
        const unsigned expected = 10000 - ((10000 - n) % 1024);
        CHECK(*reinterpret_cast<unsigned*>(watched + n * 4096) == expected);
    }
    // Revoked real permissions are never turned into writable mappings.
    watch.SetAllowed(base, 4096, false);
    CHECK(mprotect(watched, 4096, PROT_READ) == 0);
    CHECK(!watch.IsWritable(base) && !watch.HandleFault(base));
    CHECK(mprotect(watched, 4096, PROT_READ | PROT_WRITE) == 0);
    watch.SetAllowed(base, 4096, true);
    collect(); watched[17] = 2; CHECK(collect().second == 1);
    tracked.SetCached(base, watched, false);
    const auto before = faults;
    watched[19] = 3; CHECK(faults == before && collect().second == 0);
    watch.SetAllowed(base, bytes, false);
    CHECK(munmap(watched, bytes) == 0);
    signal_watch = nullptr;
    std::puts("PASS: real write faults, parallel rearming, exact dirty contents, kernel outputs, permission revocation and uncache");
    return 0;
}
