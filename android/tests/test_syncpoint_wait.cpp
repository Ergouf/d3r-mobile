#include "video_core/host1x/syncpoint_manager.h"

#include <chrono>
#include <cstdio>
#include <thread>

using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;

#define CHECK(condition) do { if (!(condition)) { \
    std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

int main() {
    Tegra::Host1x::SyncpointManager manager;
    CHECK(manager.WaitHostUntil(0, 0, Clock::now()));
    // The current value 0 is beyond UINT32_MAX after counter wraparound.
    CHECK(manager.WaitHostUntil(0, UINT32_MAX, Clock::now()));

    const auto timeout_start = Clock::now();
    CHECK(!manager.WaitHostUntil(1, 1, timeout_start + 20ms));
    CHECK(Clock::now() - timeout_start >= 15ms);
    CHECK(!manager.WaitHostUntil(1, 1, timeout_start));

    std::thread producer([&] {
        std::this_thread::sleep_for(5ms);
        manager.IncrementHost(2);
    });
    const bool woke = manager.WaitHostUntil(2, 1, Clock::now() + 2s);
    producer.join();
    CHECK(woke);
    CHECK(manager.GetHostSyncpointValue(2) == 1);

    std::thread unrelated([&] {
        std::this_thread::sleep_for(2ms);
        manager.IncrementHost(3);
    });
    const bool wrong_fence = manager.WaitHostUntil(4, 1, Clock::now() + 20ms);
    unrelated.join();
    CHECK(!wrong_fence);
    CHECK(manager.GetHostSyncpointValue(4) == 0);
    std::puts("syncpoint wait: ready, wraparound, timeout, expired deadline, wake and unrelated signal passed");
    return 0;
}
