/* Android-native signal-chain regression: no guest, no JVM, one fork per case.
 *
 * Contract install_crash_handler()/install_signal_actions()/chain_signal()/
 * crash_handler() must keep now that the host installs through libc sigaction
 * (so ART's signal chain stays ahead of the user action):
 *   - a previous user handler is chained exactly once and, for a non-guest
 *     thread, may return to the faulting code;
 *   - a non-guest thread keeps its tpidr_el0 / x18: the handler must not stamp
 *     the installing thread's stored values onto it;
 *   - a guest fault goes through the dump path, has its interrupted tp/x18
 *     restored, and still terminates with the true signal under SIG_DFL.
 *
 * SIGTRAP is used everywhere so the default action never reaches debuggerd;
 * every fatal child is bounded by a parent timeout + SIGKILL. */
#include "../host/d3_host.c"

#include <pthread.h>
#include <stdio.h>
#include <sys/resource.h>
#include <sys/wait.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

/* Plain stores only, so a handler can fill this without TLS or libc. */
struct ScReport {
    volatile sig_atomic_t calls;
    volatile sig_atomic_t siginfo_form;
    volatile sig_atomic_t sig_seen;
    volatile uint64_t live_tp;   /* tpidr seen by the previous handler */
    volatile uint64_t live_x18;  /* x18 seen by the previous handler */
    volatile uint64_t host_tp;   /* faulting thread's own tpidr */
    volatile uint64_t host_x18;
    volatile uint64_t fake_tp;   /* fake guest tpidr value */
    volatile uint64_t post_tp;   /* tpidr after the guest handler returns */
    volatile uint64_t post_x18;  /* x18 after the guest handler returns */
    volatile sig_atomic_t dump_tag;
    volatile sig_atomic_t dump_signal;
    volatile sig_atomic_t dump_guest_tid;
};

static struct ScReport *g_rpt;

static void sc_record_live_tls(void) {
    uint64_t tp, x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    __asm__ volatile("mov %0, x18" : "=r"(x18));
    g_rpt->live_tp = tp;
    g_rpt->live_x18 = x18;
}

static void sc_prev_plain(int sig) {
    g_rpt->calls++;
    g_rpt->siginfo_form = 0;
    g_rpt->sig_seen = sig;
    sc_record_live_tls();
}

static void sc_prev_siginfo(int sig, siginfo_t *si, void *uc) {
    (void)si;
    (void)uc;
    g_rpt->calls++;
    g_rpt->siginfo_form = 1;
    g_rpt->sig_seen = sig;
    sc_record_live_tls();
}

static void sc_arm_plain(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = sc_prev_plain;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTRAP, &sa, NULL);
}

static void sc_arm_siginfo(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = sc_prev_siginfo;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGTRAP, &sa, NULL);
}

static void sc_arm_default(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = SIG_DFL;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTRAP, &sa, NULL);
}

/* A chained previous handler that returns must resume here; a default action
   kills the process before this line. */
static void sc_raise_trap(void) {
    struct rlimit rl = {0, 0};
    setrlimit(RLIMIT_CORE, &rl);
    (void)raise(SIGTRAP);
    _exit(42);
}

static void sc_child_plain(void) {
    sc_arm_plain();
    install_crash_handler();
    sc_raise_trap();
}

static void sc_child_siginfo(void) {
    sc_arm_siginfo();
    install_crash_handler();
    sc_raise_trap();
}

static void sc_child_repeat(void) {
    sc_arm_plain();
    install_crash_handler();
    install_crash_handler();
    sc_raise_trap();
}

static void sc_child_default(void) {
    sc_arm_default();
    install_crash_handler();
    sc_raise_trap();
}

static void *sc_thread_fn(void *arg) {
    (void)arg;
    uint64_t tp, x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    __asm__ volatile("mov %0, x18" : "=r"(x18));
    g_rpt->host_tp = tp;
    g_rpt->host_x18 = x18;
    sc_raise_trap();
    return NULL;
}

/* Handler is installed on the chain's main thread only, so the worker is
   "unknown" to the fault-thread registry and takes the non-guest path. */
static void sc_child_thread(void) {
    sc_arm_plain();
    install_crash_handler();
    pthread_t t;
    if (pthread_create(&t, NULL, sc_thread_fn, NULL) != 0)
        _exit(43);
    pthread_join(t, NULL);
    _exit(44);
}

/* Fault on the guest thread with a fake guest tpidr and sentinel x18. The
   whole block is pure: no libc, no host TLS, only the instructions below. On
   return (non-fatal), host TLS is back and post_* hold what the handler left. */
static void sc_trigger_guest(uint64_t sentinel) {
    (void)this_guest_tls();
    thread_region_set_host_tp(host_thread_pointer());
    struct ScGuestTls {
        uint64_t word;
    } *fake = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (fake == MAP_FAILED)
        fail("fake tls mmap errno %d", errno);
    fake->word = UINT64_C(0xf001f001f001f001);
    uint64_t fake_tp = (uint64_t)(uintptr_t)fake;
    g_rpt->fake_tp = fake_tp;
    uint64_t host_tp = g_host_tp;
    uint64_t host_x18 = g_host_x18;
    size_t rpt = (size_t)(uintptr_t)g_rpt;

    __asm__ volatile(
        "mov x18, %[sentinel]\n\t"
        "mov x19, %[rpt]\n\t"
        "mov x20, %[host_tp]\n\t"
        "mov x21, %[host_x18]\n\t"
        "msr tpidr_el0, %[fake_tp]\n\t"
        "mov x8, %[tgkill]\n\t"
        "mov x0, %[pid]\n\t"
        "mov x1, %[tid]\n\t"
        "mov x2, %[trap]\n\t"
        "svc #0\n\t"                    /* handler runs, restores interrupted tp/x18 */
        "mrs x9, tpidr_el0\n\t"
        "str x9, [x19, %[off_post_tp]]\n\t"
        "mov x9, x18\n\t"
        "str x9, [x19, %[off_post_x18]]\n\t"
        "msr tpidr_el0, x20\n\t"
        "mov x18, x21\n\t"
        :
        : [sentinel] "r"(sentinel), [rpt] "r"(rpt), [host_tp] "r"(host_tp),
          [host_x18] "r"(host_x18), [fake_tp] "r"(fake_tp),
          [tgkill] "r"((long)RAW_SYS_TGKILL), [pid] "r"((long)getpid()),
          [tid] "r"((long)gettid()), [trap] "r"((long)SIGTRAP),
          [off_post_tp] "i"(offsetof(struct ScReport, post_tp)),
          [off_post_x18] "i"(offsetof(struct ScReport, post_x18))
        : "x0", "x1", "x2", "x8", "x9", "x19", "x20", "x21", "memory");
}

#define SC_SENTINEL UINT64_C(0x1234dead5678beef)

/* Read back the guest crash dump (plain libc: host TLS is restored by now). */
static void sc_check_dump(pid_t tid) {
    static char buf[8192];
    char expect[48];
    int fd = open(CRASH_PATH, O_RDONLY);
    ssize_t n = fd >= 0 ? read(fd, buf, sizeof buf - 1) : -1;
    if (fd >= 0)
        close(fd);
    if (n <= 0)
        return;
    buf[n] = 0;
    g_rpt->dump_tag = strstr(buf, "tag=d3crash") != NULL;
    /* dump_field prints every value as zero-padded 16-digit hex. */
    snprintf(expect, sizeof expect, "signal=%016" PRIx64, (uint64_t)SIGTRAP);
    g_rpt->dump_signal = strstr(buf, expect) != NULL;
    snprintf(expect, sizeof expect, "guest_tid=%016" PRIx64, (uint64_t)tid);
    g_rpt->dump_guest_tid = strstr(buf, expect) != NULL;
}

static void sc_child_guest_crash(void) {
    sc_arm_plain();
    g_guest_tid = (uint64_t)gettid();
    install_crash_handler();
    sc_trigger_guest(SC_SENTINEL);
    sc_check_dump((pid_t)gettid());
    _exit(42);
}

static void sc_child_guest_fatal(void) {
    sc_arm_default();
    g_guest_tid = (uint64_t)gettid();
    install_crash_handler();
    sc_trigger_guest(SC_SENTINEL); /* previous is SIG_DFL: does not return */
    _exit(42);
}

static void sc_sleep_ms(int ms) {
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}

/* 0 if reaped in time, 1 on timeout (after SIGKILL), -1 on wait error. */
static int sc_wait(pid_t child, int *status, int ms) {
    for (int waited = 0; waited < ms; waited += 20) {
        pid_t r = waitpid(child, status, WNOHANG);
        if (r == child)
            return 0;
        if (r < 0)
            return -1;
        sc_sleep_ms(20);
    }
    kill(child, SIGKILL);
    waitpid(child, status, 0);
    return 1;
}

static pid_t sc_fork(void (*fn)(void)) {
    memset(g_rpt, 0, sizeof *g_rpt);
    pid_t p = fork();
    if (p == 0) {
        fn();
        _exit(45); /* fn() must not return */
    }
    return p;
}

int main(void) {
    g_rpt = mmap(NULL, sizeof *g_rpt, PROT_READ | PROT_WRITE,
                 MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    CHECK(g_rpt != MAP_FAILED);

    /* The installer's TLS: a buggy path would stamp these onto a faulting
       thread. A fork()ed child inherits the same main-thread tpidr. */
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(g_host_tp));
    __asm__ volatile("mov %0, x18" : "=r"(g_host_x18));

    int status;
    pid_t child;

    /* 1. plain previous handler: chained once, its return resumes the thread. */
    child = sc_fork(sc_child_plain);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(g_rpt->calls == 1);
    CHECK(g_rpt->siginfo_form == 0);
    CHECK(g_rpt->sig_seen == SIGTRAP);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 42);

    /* 2. SA_SIGINFO previous handler chained with the same sig/siginfo. */
    child = sc_fork(sc_child_siginfo);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(g_rpt->calls == 1);
    CHECK(g_rpt->siginfo_form == 1);
    CHECK(g_rpt->sig_seen == SIGTRAP);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 42);

    /* 3. installing twice must not chain the previous handler twice. */
    child = sc_fork(sc_child_repeat);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(g_rpt->calls == 1);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 42);

    /* 4. non-guest thread keeps its own tpidr_el0 / x18. */
    child = sc_fork(sc_child_thread);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(g_rpt->calls == 1);
    CHECK(g_rpt->host_tp != 0);
    CHECK(g_rpt->live_tp == g_rpt->host_tp);
    CHECK(g_rpt->live_tp != g_host_tp);
    CHECK(g_rpt->live_x18 == g_rpt->host_x18);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 42);

    /* 5. previous SIG_DFL still exits by the true signal, not exit code 1. */
    child = sc_fork(sc_child_default);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(g_rpt->calls == 0);
    CHECK(WIFSIGNALED(status) && WTERMSIG(status) == SIGTRAP);

    /* 6. guest thread: the handler runs the chain on the registered host TLS,
       restores the interrupted (fake guest) tp/x18 before returning, and writes
       the crash dump. */
    child = sc_fork(sc_child_guest_crash);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(g_rpt->calls == 1);
    CHECK(g_rpt->live_tp == g_host_tp);        /* chain ran on registered host TLS */
    CHECK(g_rpt->live_tp != g_rpt->fake_tp);
    CHECK(g_rpt->live_x18 == g_host_x18);
    CHECK(g_rpt->post_tp == g_rpt->fake_tp);   /* interrupted tp restored */
    CHECK(g_rpt->post_x18 == SC_SENTINEL);     /* interrupted x18 restored */
    CHECK(g_rpt->dump_tag && g_rpt->dump_signal && g_rpt->dump_guest_tid);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 42);

    /* 7. guest fatal fault under SIG_DFL still exits by the true signal. */
    child = sc_fork(sc_child_guest_fatal);
    CHECK(child > 0);
    CHECK(sc_wait(child, &status, 3000) == 0);
    CHECK(!WIFEXITED(status));
    CHECK(WIFSIGNALED(status) && WTERMSIG(status) == SIGTRAP);

    puts("PASS: previous handler chained once, non-guest TLS preserved, "
         "guest TLS restored with dump, default fatal exits by signal");
    return 0;
}
