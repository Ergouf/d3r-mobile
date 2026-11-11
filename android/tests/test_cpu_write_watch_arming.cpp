#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <csignal>
#include <thread>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

static std::atomic<bool> protected_ready{}, fault_started{}, release_protection{};
static long arming_test_syscall(long number, ...);
#ifndef D3_ARMING_TEST_WATCH_HEADER
#define D3_ARMING_TEST_WATCH_HEADER "../gpu/host/cpu_write_watch.h"
#endif
// Delay only the test's protection syscall return, after the real kernel has
// made the page read-only. Production code contains no test hooks.
#define syscall arming_test_syscall
#include D3_ARMING_TEST_WATCH_HEADER
#undef syscall

static long arming_test_syscall(long number, ...) {
    if (number != SYS_mprotect) _exit(98);
    va_list args;
    va_start(args, number);
    void* address = va_arg(args, void*);
    const auto size = va_arg(args, std::size_t);
    const int protection = va_arg(args, int);
    va_end(args);
    const long result = ::syscall(number, address, size, protection);
    if (!result && protection == PROT_READ) {
        protected_ready.store(true, std::memory_order_release);
        while (!release_protection.load(std::memory_order_acquire)) std::this_thread::yield();
    }
    return result;
}

static D3::CpuWriteWatch* active_watch;
static void write_fault(int signal, siginfo_t* info, void*) {
    fault_started.store(true, std::memory_order_release);
    if (signal == SIGSEGV && active_watch &&
        active_watch->HandleFault(reinterpret_cast<std::uintptr_t>(info->si_addr))) return;
    dprintf(2, "FAIL: write fault rejected during first mprotect/Active publication\n");
    _exit(99);
}

#define CHECK(condition) do { if (!(condition)) { \
    std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

int main() {
    alarm(5);
    D3::CpuWriteWatch watch;
    active_watch = &watch;
    struct sigaction action{};
    action.sa_sigaction = write_fault;
    action.sa_flags = SA_SIGINFO;
    CHECK(sigaction(SIGSEGV, &action, nullptr) == 0);
    auto* page = static_cast<volatile unsigned char*>(mmap(nullptr, 4096, PROT_READ | PROT_WRITE,
                                                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    CHECK(page != MAP_FAILED);
    const auto address = reinterpret_cast<std::uintptr_t>(page);
    CHECK(watch.AddRange(address, 4096));
    watch.SetAllowed(address, 4096, true);
    bool initially_clean = true;
    std::thread armer([&] { initially_clean = watch.IsClean(address); });
    std::thread releaser([] {
        while (!fault_started.load(std::memory_order_acquire)) std::this_thread::yield();
        // The handler has to observe Busy before the armer can publish Active.
        usleep(20000);
        release_protection.store(true, std::memory_order_release);
    });
    while (!protected_ready.load(std::memory_order_acquire)) std::this_thread::yield();
    *page = 0x5a;
    armer.join();
    releaser.join();
    CHECK(!initially_clean && *page == 0x5a && watch.FaultCount() == 1);
    watch.SetAllowed(address, 4096, false);
    CHECK(munmap(reinterpret_cast<void*>(address), 4096) == 0);
    alarm(0);
    std::puts("PASS: real concurrent write waits for first-arm publication and resumes exactly once");
    return 0;
}
