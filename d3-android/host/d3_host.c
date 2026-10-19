#define _GNU_SOURCE
#include "d3_host.h"
#include "d3_service.h"
#include "d3_sync.h"
#include "../guest_layout.h"
#include "guest_relocs.h"
#include "d3_content.h"
#include "d3_display.h"
#ifdef D3_WITH_GPU
#include "../gpu/host/gpu_bridge.h"
#endif

#include <android/log.h>
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <inttypes.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <dirent.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <ucontext.h>
#include <unistd.h>

/* Phase 4. The veneer enters d3_hle_dispatch on the host TLS. The SVCs the guest
   uses during boot are implemented here; svc #0x1f ConnectToNamedPort, #0x21/#0x22
   SendSyncRequest and #0x23 SendAsyncRequest go to the service layer in
   d3_service.c. Anything still missing logs and aborts. */

#define LOG_TAG "D3Host"
#define STACK_SIZE (8u * 1024u * 1024u)
#define STACK_REGION_SIZE (1ull << 30)
#define GUARD_SIZE 0x4000u
#define PAGE_SIZE 0x4000u
#define EXC_SIZE 0x2000u
#define ALTSTACK_SIZE 0x10000u
/* GetInfo(2)/(3) alias region of a 39-bit process. The game reserves 768 MiB
   out of it for its own allocator, so 512 MiB is too small. The pages are
   committed on demand through MapPhysicalMemory. */
#define ALIAS_SIZE (64ull * 1024u * 1024u * 1024u)
#define D3_TITLE_ID 0x01001b300b9be000ull
#define TRACE_MAX 32
#define CRASH_PATH D3_PRIVATE_ROOT "/files/d3-crash.txt"
#define CRASH_PATH_FALLBACK D3_PRIVATE_ROOT "/cache/d3-crash.txt"
#define CRASH_PATH_SDCARD D3_DATA_ROOT "/logs/d3-crash.txt"
#define PROBE_INFO_PATH D3_DATA_ROOT "/logs/d3-sysinfo.txt"
#define SYS_RES_TOTAL 0x2000000ull
#define SYS_RES_USED 0x400000ull

static uint32_t g_display_width = 1600, g_display_height = 900;

int d3_host_configure_display(uint32_t width, uint32_t height) {
    if (width < 1600 || width > 4096 || height != 900) return -1;
    g_display_width = width; g_display_height = height;
    return 0;
}

enum {
    MEM_FREE = 0,
    MEM_CODE = 3,
    MEM_CODE_DATA = 4,
    MEM_NORMAL = 5,
    MEM_STACK = 11,
    MEM_THREAD_LOCAL = 12,
    MEM_INACCESSIBLE = 16
};

enum { PERM_R = 1, PERM_W = 2, PERM_X = 4, PERM_RW = 3 };

/* svc #41 GetInfo info ids, the Horizon order. */
enum {
    I_CORE_MASK = 0,
    I_PRIORITY_MASK = 1,
    I_ALIAS_ADDR = 2,
    I_ALIAS_SIZE = 3,
    I_HEAP_ADDR = 4,
    I_HEAP_SIZE = 5,
    I_TOTAL_MEM = 6,
    I_USED_MEM = 7,
    I_DEBUGGER_ATTACHED = 8,
    I_RESOURCE_LIMIT = 9,
    I_IDLE_TICK = 10,
    I_RANDOM_ENTROPY = 11,
    I_ASLR_ADDR = 12,
    I_ASLR_SIZE = 13,
    I_STACK_ADDR = 14,
    I_STACK_SIZE = 15,
    I_SYS_RES_TOTAL = 16,
    I_SYS_RES_USED = 17,
    I_PROGRAM_ID = 18,
    I_INIT_PROC_ID_RANGE = 19,
    I_USER_EXC_ADDR = 20,
    I_TOTAL_NON_SYS = 21,
    I_USED_NON_SYS = 22,
    I_IS_APPLICATION = 23
};

typedef struct {
    uint64_t addr;
    uint64_t size;
    uint32_t state;
    uint32_t attr;
    uint32_t perm;
    uint32_t ipc;
    uint32_t device;
    uint32_t pad;
} MemInfo;

typedef struct {
    uint64_t base;
    uint64_t size;
    uint32_t state;
    uint32_t perm;
} Region;

_Static_assert(sizeof(d3_saved) == 0x180, "d3_saved frame");
_Static_assert(offsetof(d3_saved, nzcv) == 0xF8, "nzcv slot");
_Static_assert(offsetof(d3_saved, q) == 0x100, "q slots");
_Static_assert(sizeof(MemInfo) == 0x28, "Horizon MemoryInfo");

__attribute__((format(printf, 1, 2)))
static void info(const char *fmt, ...) {
    char line[1024];
    int head = snprintf(line, sizeof line, "t%ld: ", (long)syscall(SYS_gettid));
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line + head, sizeof line - (size_t)head, fmt, ap);
    va_end(ap);
    __android_log_write(ANDROID_LOG_INFO, LOG_TAG, line);
}

static void __attribute__((noreturn)) __attribute__((format(printf, 1, 2))) fail(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    __android_log_vprint(ANDROID_LOG_ERROR, LOG_TAG, fmt, ap);
    va_end(ap);
    abort();
}

static void *g_guest;
static Elf64_Phdr *g_guest_phdr;
static size_t g_guest_phnum;
static uint64_t *g_table;
static uint64_t g_bias;
static size_t g_os_page;
static uint64_t g_host_tp;
static uint64_t g_host_x18;
static uint64_t g_guest_tp;
static uint64_t g_guest_x18;
static uint64_t g_heap;
static uint64_t g_heap_cap;
static uint64_t g_heap_cur;
static uint64_t g_stack;
static uint64_t g_guard;
static uint64_t g_stack_region;
static uint64_t g_tlr;
static uint64_t g_alias;
static uint64_t g_alias_cap;
static uint64_t g_exc;
static uint64_t g_image;
static uint64_t g_tick_base;
static uint64_t g_svcs;

/* The last dispatch events, so a fatal signal can report what the guest was doing.
   "after" is the guest address the stub will resume at, which names the caller. */
static struct {
    uint64_t kind;
    uint64_t extra;
    uint64_t after;
    uint64_t arg0;
} g_trace[TRACE_MAX];
static uint32_t g_trace_count;
/* The last dispatches in order, newest last. g_seen only keeps the first few of
   each id, which is useless once the guest is deep in startup. */
typedef struct {
    uint64_t kind;
    uint64_t extra;
    uint64_t lr;
    uint64_t x0;
} D3Ring;
static D3Ring g_ring[16];
static uint32_t g_ring_next;
static uint64_t g_guest_tid;
static uint64_t g_last_kind;
static uint64_t g_last_extra;

static uint64_t this_guest_tls(void);
static uint64_t current_guest_region(void);
static int is_guest_region(uint64_t tls);
static int thread_is_guest(pid_t tid);
static uint64_t hook_guest_tp(void);
static uint32_t guest_thread_id(uint64_t thread_tp);

/* Dump the calling thread's guest TLS identity: region, thread object and the
   id the SDK compares mutex owners against. */
static void log_guest_region(const char *what) {
    const uint64_t tlr = current_guest_region();
    const uint64_t tp = tlr - 0x4000;
    const uint64_t thread = tlr ? *(const uint64_t *)(uintptr_t)(tlr + 0x1f8) : 0;
    const uint32_t id = thread ? *(const uint32_t *)(uintptr_t)(thread + 0x1b0) : 0;
    info("%s tid=%ld tls=%#" PRIx64 " tlr=%#" PRIx64 " thread=%#" PRIx64 " id=%#x",
         what, (long)gettid(), tp, tlr, thread, (unsigned)id);
}


/* Per-thread host TLS for the hook trampolines, plus the guest return address of
   the hook call that is currently running (which is what names the call site of
   an nn::diag::AbortImpl in the logs). */
#define GUEST_TLS_SIZE 0xC000u
#define GUEST_TLR_OFFSET 0x4000u
#define GUEST_THREAD_OFFSET 0x8000u

/* A guest thread may replace tpidr_el0 with a TLS block the SDK allocated for
   itself (nn::os does that during nninitStartup), so tpidrro_el0 can no longer be
   derived from the thread pointer.  Each thread therefore keeps the region this
   host allocated for it, and the dispatcher maps the thread pointer back to that
   region: the read-only thread pointer is what carries the message buffer and the
   per-thread thread object the SDK compares mutex owners against. */
#define MAX_TP_MAP 64
static struct {
    uint64_t tp;
    uint64_t tls;
} g_tp_map[MAX_TP_MAP];
static int g_tp_map_count;

static void tp_map_add(uint64_t tp, uint64_t tls) {
    if (!tp || !tls)
        return;
    for (int index = 0; index < g_tp_map_count; index++) {
        if (g_tp_map[index].tp == tp) {
            g_tp_map[index].tls = tls;
            return;
        }
    }
    if (g_tp_map_count < MAX_TP_MAP) {
        g_tp_map[g_tp_map_count].tp = tp;
        g_tp_map[g_tp_map_count].tls = tls;
        __atomic_store_n(&g_tp_map_count, g_tp_map_count + 1, __ATOMIC_RELEASE);
    }
}

static uint64_t guest_tls_for_tp(uint64_t tp) {
    const int count = __atomic_load_n(&g_tp_map_count, __ATOMIC_ACQUIRE);
    for (int index = 0; index < count; index++) {
        if (g_tp_map[index].tp == tp)
            return g_tp_map[index].tls;
    }
    return 0;
}

/* The read-only thread pointer of the dispatching thread. */
/* The title's own code re-points tpidr_el0 at its module TLS during main
   DT_INIT, which has nothing to do with the region this host allocated for the
   thread.  tpidrro_el0 still has to name that region, so the dispatcher falls
   back to the host thread id, which guest_call recorded per thread. */
static struct {
    uint64_t tid;
    uint64_t tls;
} g_tid_map[MAX_TP_MAP];
static int g_tid_map_count;

static void tid_map_set(uint64_t tid, uint64_t tls) {
    if (!tid || !tls)
        return;
    for (int index = 0; index < g_tid_map_count; index++) {
        if (g_tid_map[index].tid == tid) {
            g_tid_map[index].tls = tls;
            return;
        }
    }
    if (g_tid_map_count < MAX_TP_MAP) {
        g_tid_map[g_tid_map_count].tid = tid;
        g_tid_map[g_tid_map_count].tls = tls;
        __atomic_store_n(&g_tid_map_count, g_tid_map_count + 1, __ATOMIC_RELEASE);
    }
}

static uint64_t tid_map_get(uint64_t tid) {
    const int count = __atomic_load_n(&g_tid_map_count, __ATOMIC_ACQUIRE);
    for (int index = 0; index < count; index++) {
        if (g_tid_map[index].tid == tid)
            return g_tid_map[index].tls;
    }
    return 0;
}

static uint64_t guest_tlr_for_tp(uint64_t tp) {
    uint64_t tls = this_guest_tls();
    if (!tls)
        tls = guest_tls_for_tp(tp);
    if (tls && !is_guest_region(tls))
        tls = 0;
    if (!tls) {
        tls = tid_map_get((uint64_t)syscall(SYS_gettid));
        if (tls && !is_guest_region(tls))
            tls = 0;
    }
    /* A thread that never re-entered the veneer through guest_call (a title
       thread, or the very first dispatch on a worker) has no map entry; falling
       back to the title's own thread pointer then gives it a *different* thread
       object than the one it used earlier, so nn::os TLS slots read back as NULL.
       The calling thread's own region is always the right answer. */
    const uint64_t from_map = tls;
    if (!tls)
        tls = tid_map_get((uint64_t)syscall(SYS_gettid));
    const uint64_t from_tid = tls;
    if (!tls)
        tls = this_guest_tls();
    const uint64_t from_self = tls;
    if (!tls)
        tls = tp;
    if (from_map == 0 && from_tid == 0 && from_self == 0) {
        static int logs;
        if (logs < 8) {
            logs++;
            info("tlr: unresolved tp=%#" PRIx64 " tid=%ld self=%#" PRIx64, tp,
                 (long)syscall(SYS_gettid), this_guest_tls());
        }
    }
    if (tp && tls && tp != tls)
        tp_map_add(tp, tls);
    const uint64_t region = tls;
    const uint64_t tlr = region + GUEST_TLR_OFFSET;
    /* The kernel guarantees that every thread's read-only region points at a
       thread object; a zero there makes nn::os dereference NULL (SIGSEGV at
       0x1b0).  The title's own TLS setup never fills this host-owned page. */
    if (tls && tlr && *(const uint64_t *)(uintptr_t)(tlr + 0x1f8) == 0)
        *(uint64_t *)(uintptr_t)(tlr + 0x1f8) = region + GUEST_THREAD_OFFSET;
    return tlr;
}


/* Non-static because hook_stub.S publishes the guest return address and thread
   pointer here on every hook entry; the offsets (0/8/16) are fixed in that file
   and in hook_guest_tp()'s callers. */
struct {
    uint64_t guest_lr;
    uint64_t host_tp;
    uint64_t guest_tp;
} g_hook_tls;

static uint32_t g_info_logs;
static uint64_t g_tls;
static uint64_t g_thread;
static int g_started;
static int g_regions_logged;
static int g_found_guest;
static uint32_t g_query_logs;

enum { MAX_FIXED = 256, MAX_REG = 2048, MAX_STACK_MAPS = 256 };
typedef struct {
    uint64_t destination;
    uint64_t source;
    uint64_t size;
    uint32_t source_state;
    uint32_t source_perm;
} StackMap;
static StackMap g_stack_maps[MAX_STACK_MAPS];
static Region g_fixed[MAX_FIXED];
static int g_nfixed;
static Region g_reg[MAX_REG];
static int g_nreg;

static char g_arg0[] = "D3";
static char *g_argv[] = {g_arg0, 0};

static const char *module_of(uint64_t address) {
    if (!g_bias || address < g_bias)
        return "host";
    for (size_t i = 0; i < g_guest_phnum; i++) {
        const Elf64_Phdr *ph = &g_guest_phdr[i];
        uint64_t start = g_bias + ph->p_vaddr;
        if (ph->p_type != PT_LOAD || address < start || address >= start + ph->p_memsz)
            continue;
        if (ph->p_vaddr == D3_SDK_BASE)
            return "sdk";
        if (ph->p_vaddr == D3_MAIN_BASE)
            return "main";
        if (ph->p_vaddr == D3_VENEER_BASE)
            return "veneer";
        return "guest";
    }
    return "host";
}

/* A fault can arrive while the guest owns tpidr_el0 and x18, and it can arrive on
   a thread that was not created by guest_thread, so the dump is written with raw
   syscalls: no libc, no errno, no TLS and no lazy PLT binding. The libc copy is
   only attempted afterwards, for logcat. */
static long raw_syscall4(long number, long a0, long a1, long a2, long a3) {
    register long x0 __asm__("x0") = a0;
    register long x1 __asm__("x1") = a1;
    register long x2 __asm__("x2") = a2;
    register long x3 __asm__("x3") = a3;
    register long x8 __asm__("x8") = number;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
    return x0;
}

static long raw_syscall6(long number, long a0, long a1, long a2, long a3, long a4, long a5) {
    register long x0 __asm__("x0") = a0;
    register long x1 __asm__("x1") = a1;
    register long x2 __asm__("x2") = a2;
    register long x3 __asm__("x3") = a3;
    register long x4 __asm__("x4") = a4;
    register long x5 __asm__("x5") = a5;
    register long x8 __asm__("x8") = number;
    __asm__ volatile("svc #0" : "+r"(x0)
                     : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory");
    return x0;
}

#define RAW_SYS_OPENAT 56
#define RAW_SYS_CLOSE 57
#define RAW_SYS_WRITE 64
#define RAW_SYS_GETTID 178
#define RAW_AT_FDCWD (-100)
#define RAW_O_WRONLY 01
#define RAW_O_CREAT 0100
#define RAW_O_TRUNC 01000
#define RAW_SYS_RT_SIGACTION 134
#define RAW_SYS_RT_SIGPROCMASK 135
#define RAW_SYS_TGKILL 131
#define RAW_SYS_GETPID 172
#define RAW_SYS_EXIT_GROUP 94
#define RAW_SYS_PROCESS_VM_READV 270

static char g_dump[65536];
static uint32_t g_dump_used;

static void dump_bytes(const char *text, uint32_t count) {
    if (count > sizeof g_dump - g_dump_used)
        return;
    memcpy(g_dump + g_dump_used, text, count);
    g_dump_used += count;
}

static void dump_text(const char *text) {
    dump_bytes(text, (uint32_t)strlen(text));
}

static void dump_hex(uint64_t value) {
    static const char digits[] = "0123456789abcdef";
    char line[17];
    for (int i = 0; i < 16; i++)
        line[i] = digits[(value >> ((15 - i) * 4)) & 0xF];
    line[16] = 10;
    dump_bytes(line, 17);
}

static void dump_field(const char *label, uint64_t value) {
    dump_text(label);
    dump_text("=");
    dump_hex(value);
}

static void dump_index(const char *prefix, uint32_t index, uint64_t value) {
    char label[8];
    label[0] = prefix[0];
    if (index < 10) {
        label[1] = (char)('0' + index);
        label[2] = 0;
    } else {
        label[1] = (char)('0' + index / 10u);
        label[2] = (char)('0' + index % 10u);
        label[3] = 0;
    }
    dump_field(label, value);
}

static int safe_read(uint64_t address, void *dst, uint64_t size);

/* Prints the string a word points at, but only when it really is one: an abort
   records its message as a const char* on the faulting stack. */
static uint32_t dump_string(uint64_t address) {
    unsigned char text[40];
    uint32_t printable = 0;
    if (address < g_bias || address >= g_bias + 0x3400000u)
        return 0;
    if (!safe_read(address, text, sizeof text))
        return 0;
    while (printable < sizeof text) {
        unsigned char c = text[printable];
        if (c < 0x20 || c > 0x7e)
            break;
        printable++;
    }
    if (printable < 6)
        return 0;
    dump_bytes((const char *)text, printable);
    return printable;
}

/* The abort string pointers sit above the faulting frame, so the words over the
   stack pointer are walked as well. */
static void dump_stack_strings(uint64_t stack) {
    uint64_t words[256];
    uint32_t found = 0;
    if (!safe_read(stack, words, sizeof words))
        return;
    for (uint32_t i = 0; i < 256 && found < 32; i++) {
        uint32_t before = g_dump_used;
        char label[8];
        if (words[i] < g_bias || words[i] >= g_bias + 0x3400000u)
            continue;
        label[0] = 'y';
        label[1] = (char)('0' + (i / 100u) % 10u);
        label[2] = (char)('0' + (i / 10u) % 10u);
        label[3] = (char)('0' + i % 10u);
        label[4] = 0;
        dump_text(label);
        dump_text("=");
        if (dump_string(words[i])) {
            dump_text("\n");
            found++;
        } else {
            g_dump_used = before;
        }
    }
}

static void dump_file(const char *path) {
    long fd = raw_syscall4(RAW_SYS_OPENAT, RAW_AT_FDCWD, (long)(uintptr_t)path,
                           RAW_O_WRONLY | RAW_O_CREAT | RAW_O_TRUNC, 0600);
    if (fd < 0)
        return;
    raw_syscall4(RAW_SYS_WRITE, fd, (long)(uintptr_t)g_dump, (long)g_dump_used, 0);
    raw_syscall4(RAW_SYS_CLOSE, fd, 0, 0, 0);
}

/* arm64 rt_sigaction takes the kernel layout: handler, flags, restorer, mask. */
typedef struct {
    uint64_t handler;
    uint64_t flags;
    uint64_t restorer;
    uint64_t mask;
} D3SigAction;

typedef struct {
    uint64_t base;
    uint64_t len;
} D3Iov;

enum { MAX_FAULT_THREADS = 8 };
/* The guest owns tpidr_el0 and x18 while it runs, so a fault can arrive with the
   host TLS unreachable, and the handler has to restore it before any libc call.
   Which host values belong to the faulting thread is recorded on install. */
static struct {
    uint64_t tid;
    uint64_t tp;
    uint64_t x18;
} g_fault_threads[MAX_FAULT_THREADS];
static int g_nfault_threads;

static void remember_fault_thread(void) {
    uint64_t tid = (uint64_t)raw_syscall4(RAW_SYS_GETTID, 0, 0, 0, 0);
    uint64_t tp;
    uint64_t x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    __asm__ volatile("mov %0, x18" : "=r"(x18));
    for (int i = 0; i < g_nfault_threads; i++) {
        if (g_fault_threads[i].tid == tid) {
            g_fault_threads[i].tp = tp;
            g_fault_threads[i].x18 = x18;
            return;
        }
    }
    if (g_nfault_threads < MAX_FAULT_THREADS) {
        g_fault_threads[g_nfault_threads].tid = tid;
        g_fault_threads[g_nfault_threads].tp = tp;
        g_fault_threads[g_nfault_threads].x18 = x18;
        g_nfault_threads++;
    }
}

static void raw_sigaction(int signal, const D3SigAction *action, D3SigAction *old) {
    raw_syscall6(RAW_SYS_RT_SIGACTION, signal, (long)(uintptr_t)action, (long)(uintptr_t)old,
                 8, 0, 0);
}

static struct sigaction g_previous_signals[NSIG];
#ifdef D3_WITH_GPU
static int g_write_watch_signal;
#endif
/* The kernel slot each forced signal had before install_signal_actions took it
   over: with ART loaded that is libsigchain's trampoline. */
static D3SigAction g_kernel_signals[NSIG];
static sig_atomic_t g_signal_reset[NSIG];
static pthread_once_t g_signal_once = PTHREAD_ONCE_INIT;

extern void crash_handler(int sig, siginfo_t *si, void *context);

/* Hand a signal back to whatever owned the kernel slot before the forcing: ART
   resolves null checks in compiled code (and GC read barriers) by faulting and
   resuming, and libsigchain dispatches those to its own handler, which the
   forced slot otherwise hides behind SIG_DFL.  The signal stays pending while
   this handler runs, so it is delivered again on return. */
static int chain_kernel(int sig) {
    const D3SigAction saved = g_kernel_signals[sig];
    if (!saved.handler || saved.handler == (uint64_t)(uintptr_t)crash_handler)
        return 0;
    const uint64_t mask = UINT64_C(1) << (sig - 1);
    raw_sigaction(sig, &saved, 0);
    raw_syscall6(RAW_SYS_TGKILL, raw_syscall4(RAW_SYS_GETPID, 0, 0, 0, 0),
                 raw_syscall4(RAW_SYS_GETTID, 0, 0, 0, 0), sig, 0, 0, 0);
    raw_syscall6(RAW_SYS_RT_SIGPROCMASK, SIG_UNBLOCK, (long)(uintptr_t)&mask, 0, sizeof mask, 0, 0);
    return 1;
}

static void default_signal(int sig) {
    D3SigAction action = {0};
    uint64_t mask = UINT64_C(1) << (sig - 1);
    raw_sigaction(sig, &action, 0);
    raw_syscall6(RAW_SYS_TGKILL, raw_syscall4(RAW_SYS_GETPID, 0, 0, 0, 0),
                 raw_syscall4(RAW_SYS_GETTID, 0, 0, 0, 0), sig, 0, 0, 0);
    raw_syscall6(RAW_SYS_RT_SIGPROCMASK, SIG_UNBLOCK, (long)(uintptr_t)&mask,
                 0, sizeof mask, 0, 0);
}

static void chain_signal(int sig, siginfo_t *si, void *context) {
    const struct sigaction *previous = &g_previous_signals[sig];
    if (previous->sa_handler == SIG_IGN) {
        if (si && si->si_code > 0)
            default_signal(sig);
        return;
    }
    if (previous->sa_handler == SIG_DFL ||
        ((previous->sa_flags & SA_RESETHAND) &&
         __atomic_exchange_n(&g_signal_reset[sig], 1, __ATOMIC_RELAXED))) {
        default_signal(sig);
        return;
    }
    if (previous->sa_flags & SA_SIGINFO)
        previous->sa_sigaction(sig, si, context);
    else
        previous->sa_handler(sig);
}

/* process_vm_readv on our own pid reports a bad address instead of faulting, which
   is what dumping a stack pointer needs. */
static int safe_read(uint64_t address, void *dst, uint64_t size) {
    D3Iov local;
    D3Iov remote;
    if (!address || !size)
        return 0;
    local.base = (uint64_t)(uintptr_t)dst;
    local.len = size;
    remote.base = address;
    remote.len = size;
    return raw_syscall6(RAW_SYS_PROCESS_VM_READV, raw_syscall4(RAW_SYS_GETPID, 0, 0, 0, 0),
                        (long)(uintptr_t)&local, 1, (long)(uintptr_t)&remote, 1, 0) == (long)size;
}


/* Write into guest memory through the kernel: never trust the pointer (a bad one
   would fault the whole emulator), and report whether it landed. */
static void dump_memory_links(uint32_t reg, uint64_t address) {
    uint64_t words[24];
    dump_field("m_register", reg);
    for (uint32_t depth = 0; depth < 2; depth++) {
        dump_field("m_depth", depth);
        dump_field("m_address", address);
        if (!safe_read(address, words, sizeof words)) {
            dump_text("m_unreadable\n");
            return;
        }
        for (uint32_t i = 0; i < 24; i++)
            dump_index("m", i, words[i]);
        address = words[0];
    }
}

static void dump_resource_cache(uint64_t manager) {
    uint64_t fields[0x150 / 8];
    uint64_t dictionary;
    if (!safe_read(manager + 0x20, &dictionary, sizeof dictionary) ||
        !safe_read(dictionary, fields, sizeof fields))
        return;
    dump_field("cache_dictionary", dictionary);
    for (uint32_t index = 0; index < sizeof fields / sizeof fields[0]; index++)
        dump_index("cd", index, fields[index]);
    const uint32_t highest = (uint32_t)fields[0x108 / 8];
    const uint64_t table = fields[0x120 / 8];
    if (highest >= 0x3ffff || !table)
        return;
    uint32_t occupied = 0, referenced = 0, flagged = 0, eligible = 0, unreadable = 0;
    uint64_t entries[512];
    for (uint32_t base = 0; base <= highest; base += 256) {
        const uint32_t count = highest - base + 1 < 256 ? highest - base + 1 : 256;
        if (!safe_read(table + (uint64_t)base * 16, entries, (uint64_t)count * 16))
            break;
        for (uint32_t index = 0; index < count; index++) {
            const uint64_t key = entries[index * 2];
            const uint64_t pointer = entries[index * 2 + 1];
            if ((uint32_t)key == UINT32_MAX || !pointer)
                continue;
            uint32_t header[4];
            occupied++;
            if (!safe_read(pointer, header, sizeof header)) {
                unreadable++;
                continue;
            }
            referenced += header[1] != 0;
            flagged += (header[2] & 1u) != 0;
            eligible += header[1] == 0 && !(header[2] & 1u);
            if (occupied <= 24) {
                dump_field("resource_slot", base + index);
                dump_field("resource_key", key);
                dump_field("resource_address", pointer);
                dump_field("resource_id", header[0]);
                dump_field("resource_refs", header[1]);
                dump_field("resource_flags", header[2]);
                dump_field("resource_aux", header[3]);
            }
        }
    }
    dump_field("cache_occupied", occupied);
    dump_field("cache_referenced", referenced);
    dump_field("cache_flagged", flagged);
    dump_field("cache_eligible", eligible);
    dump_field("cache_unreadable", unreadable);
}

/* Some guest code reads the *physical* counter (mrs Xt, cntpct_el0), which is
   trapped at EL0 on Android: it arrives here as SIGILL and used to kill the
   process.  Emulate it from the virtual counter, which runs at the same rate. */
static int emulate_counter_read(mcontext_t *mc) {
    const uint32_t *pc = (const uint32_t *)(uintptr_t)mc->pc;
    uint32_t insn = 0;
    if (!pc)
        return 0;
    insn = *pc;
    if ((insn & 0xFFFFFFE0u) != 0xD53BE020u) /* mrs Xt, cntpct_el0 */
        return 0;
    uint64_t now = 0;
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(now));
    mc->regs[insn & 31u] = now;
    mc->pc = (uint64_t)(uintptr_t)(pc + 1);
    return 1;
}

/* Whether this tid ever entered guest code (see the definition further down). */
static int thread_is_guest(pid_t tid);

#ifdef D3_WITH_GPU
static int cpu_write_fault(const mcontext_t *mc) {
    /* ESR_EL1 signal context: accept only a data abort with WnR set. */
    const unsigned char *cursor = mc->__reserved;
    const unsigned char *end = cursor + sizeof mc->__reserved;
    while (cursor + 8 <= end) {
        uint32_t magic, size;
        memcpy(&magic, cursor, 4); memcpy(&size, cursor + 4, 4);
        if (!magic || size < 8 || (size & 15) || (size_t)(end - cursor) < size) break;
        if (magic == 0x45535201u && size >= 16) {
            uint64_t esr; memcpy(&esr, cursor + 8, 8);
            return ((esr >> 26) == 0x24 || (esr >> 26) == 0x25) && (esr & 0x40);
        }
        cursor += size;
    }
    return 0;
}
#endif

void d3_crash_handler_body(int sig, siginfo_t *si, void *context) {
    /* Only a guest fault needs its host TLS restored. Other threads must retain
       their own TLS while the preceding signal action runs. */
    ucontext_t *uc = context;
    mcontext_t *mc = &uc->uc_mcontext;
#ifdef D3_WITH_GPU
    if (sig == SIGSEGV && si && (si->si_code == SEGV_ACCERR || si->si_code == SEGV_MAPERR) && cpu_write_fault(mc) &&
        d3_gpu_handle_cpu_write_fault((uint64_t)(uintptr_t)si->si_addr))
        return;
#endif
    /* Not one of our guest threads: hand the fault back to whoever installed a
       handler before us (ART, the framework), exactly as the kernel would. */
    if (!thread_is_guest((pid_t)syscall(SYS_gettid))) {
#ifdef D3_WITH_GPU
        if (sig == SIGSEGV && g_write_watch_signal && g_kernel_signals[sig].handler &&
            g_kernel_signals[sig].handler != (uint64_t)(uintptr_t)crash_handler) {
            /* Preserve ART's original context and keep the kernel interceptor
               installed. Re-raising here loses the faulting Java instruction. */
            void (*handler)(int, siginfo_t*, void*) =
                (void (*)(int, siginfo_t*, void*))(uintptr_t)g_kernel_signals[sig].handler;
            handler(sig, si, context);
            return;
        }
#endif
        const struct sigaction *previous = &g_previous_signals[sig];
        static int framework_logs;
        if (framework_logs < 24) {
            framework_logs++;
            info("framework fault sig=%d pc=%#" PRIx64 " tid=%ld prev=%s",
                 sig, (uint64_t)(uintptr_t)mc->pc, (long)syscall(SYS_gettid),
                 previous->sa_handler == SIG_DFL ? "dfl"
                 : previous->sa_handler == SIG_IGN ? "ign"
                                                   : "handler");
        }
        if (framework_logs <= 2) {
            /* The faulting instruction and the thread pointer block say whether
               ART lost its Thread* (a TLS problem of ours) or dereferenced a
               null field of a Java object.  Read both through the kernel so a
               bad pointer cannot fault the handler itself. */
            const uint64_t pc = (uint64_t)(uintptr_t)mc->pc;
            uint64_t code[8];
            uint64_t tls[16];
            uint64_t tp = 0;
            __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
            g_dump_used = 0;
            dump_text("tag=d3fault\n");
            dump_field("sig", (uint64_t)sig);
            dump_field("pc", pc);
            dump_field("tpidr", tp);
            if (safe_read(pc - 16, code, sizeof code)) {
                for (uint32_t i = 0; i < 8; i++)
                    dump_index("code", i, code[i]);
            }
            if (safe_read(tp, tls, sizeof tls)) {
                for (uint32_t i = 0; i < 16; i++)
                    dump_index("tls", i, tls[i]);
            }
            dump_file(CRASH_PATH);
        }
        if ((previous->sa_flags & SA_SIGINFO) && previous->sa_sigaction) {
            previous->sa_sigaction(sig, si, context);
            return;
        }
        if (previous->sa_handler && previous->sa_handler != SIG_DFL &&
            previous->sa_handler != SIG_IGN) {
            previous->sa_handler(sig);
            return;
        }
        /* sigaction() cannot see ART's own handlers: libsigchain keeps them out
           of the user chain, so a slot that reads as SIG_DFL can still hold its
           trampoline.  Hand the signal back to that trampoline and re-raise
           rather than killing the process; without this an ordinary Java null
           fault in compiled code (ART resolves those by resuming at a throw
           stub) ends the whole run. */
        if (chain_kernel(sig))
            return;
        signal(sig, SIG_DFL);
        raise(sig);
        return;
    }
    /* A trapped counter read is not a fault: fix it up and resume the guest. */
    if (sig == SIGILL && emulate_counter_read(mc))
        return;
    /* A jump into unmapped memory: the dumps show the guest landing on
       0x4803xxxx/0x4805xxxx with x17 = 0, i.e. an indirect call through a NULL
       function pointer (the placeholder objects this host hands out have no
       vtable).  Name the call site and treat the call as having returned 0, so the
       engine keeps running and the next call site shows up in the log too. */
    if ((sig == SIGSEGV || sig == SIGBUS || sig == SIGILL) && mc->pc) {
        Dl_info where;
        const uint64_t pc = (uint64_t)mc->pc;
        const int known_module = dladdr((void *)(uintptr_t)pc, &where) != 0;
        const int in_guest = pc >= g_bias && pc < g_bias + 0x4000000ull;
        static int wild_logs;
        /* A target inside the image *size* but below the bias is an unrelocated
           guest vaddr: add the bias and continue there instead of dying. */
        if (!known_module && !in_guest && pc >= 0x10000ull && pc < 0x40000000ull) {
            static int bias_logs;
            if (bias_logs < 12) {
                bias_logs++;
                info("wild jump pc=%#" PRIx64 " is an unrelocated vaddr -> %#" PRIx64
                     " (caller %s+%#" PRIx64 ")",
                     pc, g_bias + pc, module_of((uint64_t)mc->regs[30]),
                     (uint64_t)mc->regs[30] >= g_bias ? (uint64_t)mc->regs[30] - g_bias : (uint64_t)0);
            }
            mc->pc = g_bias + pc;
            return;
        }
        if (!known_module && !in_guest && wild_logs < 24) {
            wild_logs++;
            Dl_info caller;
            const char *caller_name = "?";
            uint64_t caller_off = 0;
            if (dladdr((void *)(uintptr_t)(uint64_t)mc->regs[30], &caller) && caller.dli_sname) {
                caller_name = caller.dli_sname;
                caller_off = (uint64_t)(uintptr_t)(uint64_t)mc->regs[30] -
                             (uint64_t)(uintptr_t)caller.dli_saddr;
            }
            info("wild jump pc=%#" PRIx64 " lr=%#" PRIx64 " x0=%#" PRIx64 " x19=%#" PRIx64
                 " caller=%s+%#" PRIx64 " lib=%s",
                 pc, (uint64_t)mc->regs[30], (uint64_t)mc->regs[0], (uint64_t)mc->regs[19],
                 caller_name, caller_off,
                 (dladdr((void *)(uintptr_t)(uint64_t)mc->regs[30], &caller) && caller.dli_fname)
                     ? caller.dli_fname
                     : "?");
            mc->pc = (uint64_t)mc->regs[30];
            mc->regs[0] = 0;
            return;
        }
    }
    /* Veneer return trap: name the target and the caller, then take the branch. */
    if (sig == SIGTRAP && mc->pc) {
        const uint32_t insn = *(const uint32_t *)(uintptr_t)mc->pc;
        if ((insn & 0xFFFF0000u) == 0xD4220000u) {
            const uint64_t target = mc->regs[16];
            const uint64_t caller = mc->regs[30];
            static int veneer_logs;
            /* Any guest address carries the load bias in its high bits; a target
               without it (the 0x4803xxxx family in the dumps) is bogus. */
            if ((target >> 32) != (g_bias >> 32) && veneer_logs < 12) {
                veneer_logs++;
                info("veneer: target %#" PRIx64 " outside image (caller %#" PRIx64 " %s+%#"
                     PRIx64 ")",
                     target, caller, module_of(caller), caller >= g_bias ? caller - g_bias : caller);
            }
            mc->pc = target;
            return;
        }
    }
    /* Not __thread: a fault can arrive while TPIDR_EL0 still points at the guest
       TLS, and touching a thread-local then faults again, which the kernel turns
       into a silent default-action kill. */
    static volatile sig_atomic_t in_handler;
    if (in_handler) {
        /* A fault while dumping can never be reported; let the default action run. */
        default_signal(sig);
    }
    in_handler = 1;
    /* Very first thing: a TLS-free, libc-free line into the crash file.  The
       full dump walks /proc and uses dladdr, either of which can fault again
       when TPIDR_EL0 still points into guest memory. */
    {
        static const char hex[] = "0123456789abcdef";
        char line[160];
        int used = 0;
        const char *labels[3] = {"sig=", "pc=", "lr="};
        uint64_t values[3];
        values[0] = (uint64_t)sig;
        values[1] = (uint64_t)mc->pc;
        values[2] = (uint64_t)mc->regs[30];
        for (int item = 0; item < 3; ++item) {
            for (const char *p = labels[item]; *p; ++p)
                line[used++] = *p;
            line[used++] = '0';
            line[used++] = 'x';
            int started = 0;
            for (int shift = 60; shift >= 0; shift -= 4) {
                unsigned digit = (unsigned)((values[item] >> shift) & 0xf);
                if (digit || started || shift == 0) {
                    line[used++] = hex[digit];
                    started = 1;
                }
            }
            line[used++] = ' ';
        }
        line[used++] = '\n';
        long fd = raw_syscall4(RAW_SYS_OPENAT, RAW_AT_FDCWD, (long)(uintptr_t)CRASH_PATH,
                               577 /* O_WRONLY|O_CREAT|O_TRUNC */, 420 /* 0644 */);
        if (fd >= 0) {
            raw_syscall4(RAW_SYS_WRITE, fd, (long)(uintptr_t)line, used, 0);
            raw_syscall4(RAW_SYS_CLOSE, fd, 0, 0, 0);
        }
    }
    uint64_t fault_tid = (uint64_t)raw_syscall4(RAW_SYS_GETTID, 0, 0, 0, 0);
    /* Every thread is dumped: guest workers and host helper threads are just as
       fatal, and restricting the dump to the main guest thread hid several
       crashes completely. */
    const int guest_fault = fault_tid == g_guest_tid;
    uint64_t interrupted_tp;
    uint64_t interrupted_x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(interrupted_tp));
    __asm__ volatile("mov %0, x18" : "=r"(interrupted_x18));
    uint64_t fault_tp = 0;
    uint64_t fault_x18 = 0;
    int known = 0;
    uint64_t pc;
    for (int i = 0; i < g_nfault_threads; i++) {
        if (g_fault_threads[i].tid == fault_tid) {
            fault_tp = g_fault_threads[i].tp;
            fault_x18 = g_fault_threads[i].x18;
            known = 1;
            break;
        }
    }
    if (known) {
        __asm__ volatile("mov x18, %0" ::"r"(fault_x18) : "memory");
        __asm__ volatile("msr tpidr_el0, %0" ::"r"(fault_tp) : "memory");
    }
    pc = (uint64_t)mc->pc;
    uint64_t lr = (uint64_t)mc->regs[30];
    uint64_t fault = si && si->si_addr ? (uint64_t)(uintptr_t)si->si_addr
                                       : (uint64_t)mc->fault_address;
    uint64_t words[512];

    g_dump_used = 0;
    dump_text("tag=d3crash\n");
    dump_field("signal", (uint64_t)sig);
    dump_field("fault", fault);
    dump_field("tid", fault_tid);
    dump_field("guest_tid", g_guest_tid);
    dump_field("bias", g_bias);
    dump_field("pc", pc);
    dump_field("pc_off", pc >= g_bias ? pc - g_bias : pc);
    dump_field("lr", lr);
    dump_field("lr_off", lr >= g_bias ? lr - g_bias : lr);
    dump_field("sp", (uint64_t)mc->sp);
    {
        /* Faults in host code are indistinguishable by offset alone: name the
           containing host function so the dump is self-describing. */
        Dl_info host;
        if (dladdr((void *)(uintptr_t)pc, &host) && host.dli_sname) {
            dump_text("host_sym=");
            dump_text(host.dli_sname);
            dump_text("\n");
            if (host.dli_fbase)
                dump_field("host_off", pc - (uint64_t)(uintptr_t)host.dli_fbase);
        }
    }
    dump_field("host_tp", g_host_tp);
    dump_field("guest_tp", g_guest_tp);
    dump_field("last_kind", g_last_kind);
    dump_field("last_extra", g_last_extra);
    dump_field("svcs", g_svcs);
    for (uint32_t i = 0; i <= 30; i++)
        dump_index("x", i, (uint64_t)mc->regs[i]);
    for (uint32_t i = 0; i < 16; i++) {
        const D3Ring *entry = &g_ring[(g_ring_next + i) & 15u];
        dump_field("r_kind", entry->kind);
        dump_field("r_extra", entry->extra);
        dump_field("r_lr", entry->lr);
        dump_field("r_x0", entry->x0);
    }
    if (guest_fault) {
        dump_memory_links(19, (uint64_t)mc->regs[19]);
        dump_memory_links(20, (uint64_t)mc->regs[20]);
        dump_memory_links(21, (uint64_t)mc->regs[21]);
        if (pc == g_bias + 0x1a2c440u && lr == g_bias + 0x16c24b8u)
            dump_resource_cache((uint64_t)mc->regs[19]);
    }
    for (uint32_t i = 0; i < g_trace_count; i++) {
        dump_field("t_kind", g_trace[i].kind);
        dump_field("t_extra", g_trace[i].extra);
        dump_field("t_after", g_trace[i].after);
        dump_field("t_arg0", g_trace[i].arg0);
    }
    if (safe_read((uint64_t)mc->sp, words, 384 * 8)) {
        for (uint32_t i = 0; i < 384; i++) {
            char label[8];
            label[0] = 's';
            label[1] = (char)('0' + (i / 100u) % 10u);
            label[2] = (char)('0' + (i / 10u) % 10u);
            label[3] = (char)('0' + i % 10u);
            label[4] = 0;
            dump_field(label, words[i]);
        }
    } else {
        dump_text("sp_unreadable\n");
    }
    dump_stack_strings((uint64_t)mc->sp);
    if (safe_read((uint64_t)mc->regs[29], words, sizeof words)) {
        for (uint32_t i = 0; i < 16; i++) {
            char label[8];
            label[0] = 'f';
            label[1] = (char)('0' + (i / 10u) % 10u);
            label[2] = (char)('0' + i % 10u);
            label[3] = 0;
            dump_field(label, words[i]);
        }
    }
    {
        uint64_t fp = (uint64_t)mc->regs[29];
        for (uint32_t frame = 0; frame < 8; frame++) {
            if (!fp || (fp & 7u) || fp < 0x1000)
                break;
            if (!safe_read(fp, words, 24 * 8))
                break;
            for (uint32_t i = 0; i < 24; i++) {
                char label[8];
                label[0] = 'w';
                label[1] = (char)('0' + frame);
                label[2] = (char)('0' + (i / 10u) % 10u);
                label[3] = (char)('0' + i % 10u);
                label[4] = 0;
                dump_field(label, words[i]);
            }
            fp = words[0];
        }
    }
    dump_file(CRASH_PATH);
    dump_file(CRASH_PATH_FALLBACK);
    dump_file(CRASH_PATH_SDCARD);
    if (known || !thread_is_guest(fault_tid))
        chain_signal(sig, si, context);
    else
        default_signal(sig);
    __asm__ volatile("msr tpidr_el0, %0" ::"r"(interrupted_tp) : "memory");
    __asm__ volatile("mov x18, %0" ::"r"(interrupted_x18) : "memory");
}

/* /sdcard/D3/no-handler switches the crash path over to bionic debuggerd. */
static int tombstone_mode(void) {
    struct stat st;
    return stat(D3_DATA_ROOT "/no-handler", &st) == 0;
}

/* /sdcard/D3/pause holds the guest thread still so its signal state can be read. */
static int pause_requested(void) {
    struct stat st;
    return stat(D3_DATA_ROOT "/pause", &st) == 0;
}

/* /sdcard/D3/selftest-crash makes the guest thread fault on purpose. */
static int selftest_crash(void) {
    struct stat st;
    return stat(D3_DATA_ROOT "/selftest-crash", &st) == 0;
}

/* The wild jumps land in the 0x48xxxxxx range, which dladdr cannot name.  Log
   every executable mapping once at startup so the dump can be matched against the
   process layout (ours vs the framework's). */
static void log_exec_maps(void) {
    FILE *maps = fopen("/proc/self/maps", "re");
    if (!maps)
        return;
    char line[512];
    int logs = 0;
    while (logs < 40 && fgets(line, sizeof line, maps)) {
        const size_t len = strlen(line);
        if (len < 20 || strstr(line, " r-xp ") == 0)
            continue;
        char *const nl = strchr(line, '\n');
        if (nl)
            *nl = 0;
        info("map: %s", line);
        logs++;
    }
    fclose(maps);
}

/* /data/user/0/<pkg>/files/d3-host-force-signals hands the kernel slots for
   SIGSEGV/SIGBUS/SIGABRT to crash_handler.  It stays off by default: libsigchain
   owns those slots to run ART's fault manager, which resolves the null checks
   compiled Java relies on, and a forced slot turns every one of them into a dead
   process.  Our own handler still sees guest faults through libsigchain's chain. */
static int signal_force_disabled(void) {
    struct stat st;
    return stat(D3_PRIVATE_ROOT "/files/d3-host-force-signals", &st) != 0;
}

static void install_signal_actions(void) {
    static const int signals[] = {SIGSEGV, SIGBUS, SIGILL, SIGABRT, SIGFPE, SIGSYS, SIGTRAP};
    for (size_t i = 0; i < sizeof signals / sizeof signals[0]; i++) {
        int sig = signals[i];
        struct sigaction action;
        struct sigaction current;
        D3SigAction kernel;
        if (sigaction(sig, 0, &g_previous_signals[sig]) != 0)
            fail("sigaction read %d errno %d", sig, errno);
#ifdef D3_WITH_GPU
        if (sig == SIGSEGV && access(D3_DATA_ROOT "/gpu-write-watch", R_OK) == 0) {
            /* Like Eden's NCE signal chain, intercept before ART can touch the
               guest's TPIDR_EL0. Do not also register as ART's user handler:
               passing a framework fault to ART would recurse back into us. */
            raw_sigaction(sig, 0, &kernel);
            g_kernel_signals[sig] = kernel;
            D3SigAction watched = kernel;
            watched.handler = (uint64_t)(uintptr_t)crash_handler;
            watched.flags |= SA_SIGINFO;
            g_write_watch_signal = 1;
            raw_sigaction(sig, &watched, 0);
            info("sig %d CPU write-watch kernel interceptor installed", sig);
            continue;
        }
#endif
        memset(&action, 0, sizeof action);
        action.sa_sigaction = crash_handler;
        action.sa_mask = g_previous_signals[sig].sa_mask;
        /* SA_ONSTACK made the handler unrunnable on threads that never installed
           an alternate stack (ART helpers, host event threads), so their faults
           killed the process silently with no dump.  Roomy guest stacks make the
           guard-page case unlikely. */
        action.sa_flags = SA_SIGINFO |
                          (g_previous_signals[sig].sa_flags & (SA_RESTART | SA_NODEFER));
        /* libc keeps ART's special handlers ahead of this user action. */
        if (sigaction(sig, &action, 0) != 0)
            fail("sigaction install %d errno %d", sig, errno);
        if (sigaction(sig, 0, &current) != 0)
            fail("sigaction verify %d errno %d", sig, errno);
        raw_sigaction(sig, 0, &kernel);
        if (sig == SIGSEGV || sig == SIGBUS || sig == SIGABRT) {
            /* ART installs libsigchain, so the kernel slot points at its
               trampoline even though sigaction() reports our handler; a fatal
               fault then never reaches crash_handler.  Force the kernel slot,
               unless the no-force flag asks for libsigchain to keep it: ART then
               resolves the null checks its compiled code relies on, which a
               forced slot turns into process death. */
            g_kernel_signals[sig] = kernel;
            if (signal_force_disabled()) {
                info("sig %d left to libsigchain kernel=%" PRIx64, sig, kernel.handler);
            } else {
                D3SigAction forced = {0};
                forced.handler = (uint64_t)(uintptr_t)crash_handler;
                forced.flags = SA_SIGINFO | SA_RESTART;
                forced.restorer = kernel.restorer;
                forced.mask = kernel.mask;
                raw_sigaction(sig, &forced, 0);
                raw_sigaction(sig, 0, &kernel);
                info("sig %d forced kernel=%" PRIx64 " ours=%d", sig, kernel.handler,
                     kernel.handler == (uint64_t)(uintptr_t)crash_handler);
            }
        }
        info("sig %d user=%p ours=%d kernel=%" PRIx64 " chained=%d", sig,
             (void *)(uintptr_t)current.sa_sigaction, current.sa_sigaction == crash_handler,
             kernel.handler, kernel.handler != (uint64_t)(uintptr_t)crash_handler);
    }
}

static void install_crash_handler(void) {
    static __thread void *alternate;
    stack_t stack;
    if (sigaltstack(0, &stack) != 0)
        fail("sigaltstack read errno %d", errno);
    if (stack.ss_flags & SS_DISABLE) {
        if (!alternate) {
            alternate = mmap(0, ALTSTACK_SIZE, PROT_READ | PROT_WRITE,
                             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            if (alternate == MAP_FAILED)
                fail("altstack mmap errno %d", errno);
        }
        stack.ss_sp = alternate;
        stack.ss_size = ALTSTACK_SIZE;
        stack.ss_flags = 0;
        if (sigaltstack(&stack, 0) != 0)
            fail("sigaltstack errno %d", errno);
    }
    if (tombstone_mode()) {
        info("crash handler disabled, using debuggerd");
        return;
    }
    remember_fault_thread();
    int result = pthread_once(&g_signal_once, install_signal_actions);
    if (result != 0)
        fail("pthread_once signals %d", result);
}

/* ------------------------------------------------------------------ tracer */
/* /sdcard/D3/trace forks a tracer child that attaches to this process, so a fatal
   signal is reported even when the in process handler never runs. The child is the
   tracer and the parent keeps running the guest on purpose: the child only issues
   raw syscalls and never takes a libc lock, so cloning inside a multithreaded JVM
   cannot deadlock the guest path. Every stop lands in one of 256 fixed slots, so the
   file always holds the newest events and the fatal one is never lost. */
#define TRACE_PATH D3_DATA_ROOT "/logs/d3-trace.txt"
#define TRACE_SLOT 768
#define TRACE_SLOTS 256
#define TRACE_RING_OFF 0x1000
#define TRACE_STATE_OFF 0x40000
#define TRACE_MAPS_OFF 0x100000
#define RAW_SYS_READ 63
#define D3_NT_ARM_TLS 0x401

#define RAW_SYS_PTRACE 117
#define RAW_SYS_PRCTL 167
#define RAW_SYS_PWRITE64 68
#define RAW_SYS_NANOSLEEP 101
#define RAW_SYS_CLONE 220
#define RAW_SYS_WAIT4 260

#define D3_PTRACE_ATTACH 16
#define D3_PTRACE_CONT 7
#define D3_PTRACE_GETREGSET 0x4204
#define D3_PTRACE_GETSIGINFO 0x4202
#define D3_PTRACE_SETOPTIONS 0x4200
#define D3_PTRACE_O_TRACECLONE 0x00000008
#define D3_PTRACE_EVENT_CLONE 3
#define D3_NT_PRSTATUS 1
#define D3_WALL 0x40000000
#define D3_PR_SET_PTRACER 0x59616d61
#define D3_SIGCHLD 17

/* Linux arm64 user_pt_regs, which is what NT_PRSTATUS carries. */
typedef struct {
    uint64_t regs[31];
    uint64_t sp;
    uint64_t pc;
    uint64_t pstate;
} D3PtRegs;

/* siginfo_t for the fault signals: three ints, then the union. */
typedef struct {
    int32_t signo;
    int32_t error;
    int32_t code;
    int32_t pad;
    uint64_t addr;
    uint8_t remainder[104];
} D3Siginfo;

_Static_assert(sizeof(D3Siginfo) == 128, "Linux siginfo ABI");

static char g_trace_line[TRACE_SLOT];
static char g_trace_state[0x3000];
static char g_trace_maps[0x80000];
static char g_trace_comm[32];

static void t_memset(void *dst, int value, size_t size) {
    unsigned char *bytes = dst;
    while (size--)
        *bytes++ = (unsigned char)value;
}

static char *t_str(char *out, const char *text) {
    while (*text)
        *out++ = *text++;
    return out;
}

static char *t_dec(char *out, uint64_t value) {
    char digits[24];
    int count = 0;
    if (!value)
        digits[count++] = '0';
    while (value) {
        digits[count++] = (char)('0' + (int)(value % 10u));
        value /= 10u;
    }
    while (count)
        *out++ = digits[--count];
    return out;
}

static char *t_hex(char *out, uint64_t value) {
    static const char digits[] = "0123456789abcdef";
    *out++ = '0';
    *out++ = 'x';
    for (int i = 15; i >= 0; i--) {
        unsigned digit = (unsigned)((value >> ((unsigned)i * 4u)) & 0xFu);
        if (!digit && i && out[-1] == 'x')
            continue;
        *out++ = digits[digit];
    }
    return out;
}

static char *t_key(char *out, const char *name, uint64_t value) {
    out = t_str(out, name);
    *out++ = '=';
    out = t_hex(out, value);
    *out++ = 10;
    return out;
}

static char *t_reg(char *out, int index, uint64_t value) {
    out = t_str(out, "x");
    out = t_dec(out, (uint64_t)index);
    *out++ = '=';
    out = t_hex(out, value);
    *out++ = 10;
    return out;
}

static void t_sleep_ms(uint64_t ms) {
    int64_t request[2];
    request[0] = (int64_t)(ms / 1000u);
    request[1] = (int64_t)((ms % 1000u) * 1000000u);
    raw_syscall4(RAW_SYS_NANOSLEEP, (long)(uintptr_t)request, 0, 0, 0);
}

static long t_open_trace(void) {
    for (int attempt = 0; attempt < 100; attempt++) {
        long fd = raw_syscall4(RAW_SYS_OPENAT, RAW_AT_FDCWD, (long)(uintptr_t)TRACE_PATH,
                               RAW_O_WRONLY | RAW_O_CREAT | RAW_O_TRUNC, 0600);
        if (fd >= 0)
            return fd;
        t_sleep_ms(50);
    }
    return -1;
}

static long t_pwrite(long fd, uint64_t offset, const char *text, size_t size) {
    return raw_syscall4(RAW_SYS_PWRITE64, fd, (long)(uintptr_t)text, (long)size, (long)offset);
}

static int t_read_remote(pid_t target, uint64_t address, void *dst, uint64_t size) {
    D3Iov local;
    D3Iov remote;
    if (!address || !size)
        return 0;
    local.base = (uint64_t)(uintptr_t)dst;
    local.len = size;
    remote.base = address;
    remote.len = size;
    return raw_syscall6(RAW_SYS_PROCESS_VM_READV, target, (long)(uintptr_t)&local, 1,
                        (long)(uintptr_t)&remote, 1, 0) == (long)size;
}

static uint64_t t_global(pid_t target, const void *address) {
    uint64_t value = 0;
    t_read_remote(target, (uint64_t)(uintptr_t)address, &value, sizeof value);
    return value;
}

/* The guest bases are fixed by the link, so the bias is the only value that has to
   come from the tracee to name a module. */
static const char *t_module(uint64_t bias, uint64_t address) {
    uint64_t offset;
    if (!bias || address < bias)
        return "host";
    offset = address - bias;
    if (offset >= D3_HOST_TABLE && offset < D3_HOST_TABLE + 0x1000u)
        return "table";
    if (offset >= D3_NAME_BASE)
        return "names";
    if (offset >= D3_VENEER_BASE)
        return "veneer";
    if (offset >= D3_MAIN_BASE)
        return "main";
    if (offset >= D3_SDK_BASE)
        return "sdk";
    return "guest";
}

static char *t_addr(char *out, const char *name, uint64_t bias, uint64_t address) {
    out = t_str(out, name);
    *out++ = '=';
    out = t_hex(out, address);
    *out++ = ' ';
    out = t_str(out, t_module(bias, address));
    *out++ = '+';
    out = t_hex(out, (bias && address >= bias) ? address - bias : address);
    *out++ = 10;
    return out;
}

/* tpidr_el0 is not part of NT_PRSTATUS, so a host fault and a guest fault can only
   be told apart by asking for the TLS register separately. */
static uint64_t t_tls(pid_t tid) {
    uint64_t value = 0;
    D3Iov io;
    io.base = (uint64_t)(uintptr_t)&value;
    io.len = sizeof value;
    raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_GETREGSET, tid, D3_NT_ARM_TLS, (long)(uintptr_t)&io, 0, 0);
    return value;
}

/* The maps of the stopped process, so an address can be named even when it belongs
   to a library the host did not load itself. */
static void t_dump_maps(long fd, pid_t target) {
    char path[32];
    char *q = t_str(path, "/proc/");
    size_t used = 0;
    long in;
    q = t_dec(q, (uint64_t)target);
    q = t_str(q, "/maps");
    *q = 0;
    in = raw_syscall4(RAW_SYS_OPENAT, RAW_AT_FDCWD, (long)(uintptr_t)path, 0, 0);
    if (in < 0) {
        t_pwrite(fd, TRACE_MAPS_OFF, "maps open failed\n", 17);
        return;
    }
    while (used + 1024u <= sizeof g_trace_maps) {
        long got = raw_syscall4(RAW_SYS_READ, in, (long)(uintptr_t)(g_trace_maps + used), 1024, 0);
        if (got <= 0)
            break;
        used += (size_t)got;
    }
    raw_syscall4(RAW_SYS_CLOSE, in, 0, 0, 0);
    t_pwrite(fd, TRACE_MAPS_OFF, g_trace_maps, used);
}

static void t_state(long fd, pid_t target, uint64_t index, pid_t tid, int sig, int event,
                    const D3PtRegs *regs, const D3Siginfo *info) {
    uint64_t bias = t_global(target, &g_bias);
    uint64_t stack_base = t_global(target, &g_stack);
    uint64_t fp = regs->regs[29];
    uint64_t sp = regs->sp;
    char *p = g_trace_state;
    char *end = g_trace_state + sizeof g_trace_state - 128;
    p = t_str(p, "tag=d3trace state\n");
    p = t_key(p, "index", index);
    p = t_key(p, "tid", (uint64_t)tid);
    /* The name of the thread that faulted decides whether host code ran on the
       wrong thread or the guest thread itself misbehaved. */
    {
        char path[48];
        char *q = t_str(path, "/proc/");
        long in;
        q = t_dec(q, (uint64_t)target);
        q = t_str(q, "/task/");
        q = t_dec(q, (uint64_t)tid);
        q = t_str(q, "/comm");
        *q = 0;
        in = raw_syscall4(RAW_SYS_OPENAT, RAW_AT_FDCWD, (long)(uintptr_t)path, 0, 0);
        if (in >= 0) {
            long got = raw_syscall4(RAW_SYS_READ, in, (long)(uintptr_t)g_trace_comm, 32, 0);
            raw_syscall4(RAW_SYS_CLOSE, in, 0, 0, 0);
            if (got > 0) {
                p = t_str(p, "comm=");
                for (long i = 0; i < got; i++) {
                    char c = g_trace_comm[i];
                    if (c && c != 10)
                        *p++ = c;
                }
                *p++ = 10;
            }
        }
    }
    p = t_key(p, "sig", (uint64_t)sig);
    p = t_key(p, "event", (uint64_t)event);
    p = t_key(p, "code", (uint64_t)(int64_t)info->code);
    p = t_key(p, "addr", info->addr);
    p = t_key(p, "pstate", regs->pstate);
    p = t_addr(p, "pc", bias, regs->pc);
    p = t_addr(p, "lr", bias, regs->regs[30]);
    p = t_key(p, "sp", sp);
    p = t_key(p, "bias", bias);
    p = t_key(p, "stack", stack_base);
    p = t_key(p, "svcs", t_global(target, &g_svcs));
    p = t_key(p, "alias", t_global(target, &g_alias));
    p = t_key(p, "guest_tp", t_global(target, &g_guest_tp));
    p = t_key(p, "guest_x18", t_global(target, &g_guest_x18));
    p = t_key(p, "host_tp", t_global(target, &g_host_tp));
    p = t_key(p, "host_x18", t_global(target, &g_host_x18));
    p = t_key(p, "tlr", t_global(target, &g_tlr));
    p = t_key(p, "guard", t_global(target, &g_guard));
    {
        uint64_t host_tp = t_global(target, &g_host_tp);
        uint64_t guest_tp = t_global(target, &g_guest_tp);
        uint64_t tpidr = t_tls(tid);
        p = t_key(p, "tpidr", tpidr);
        p = t_str(p, "tpidr_owner=");
        p = t_str(p, tpidr == host_tp ? "host" : (tpidr == guest_tp ? "guest" : "other"));
        *p++ = 10;
    }
    p = t_key(p, "last_kind", t_global(target, &g_last_kind));
    p = t_key(p, "last_extra", t_global(target, &g_last_extra));
    p = t_key(p, "ring_next", t_global(target, &g_ring_next));
    for (int i = 0; i <= 30 && p < end; i++)
        p = t_reg(p, i, regs->regs[i]);
    /* The newest dispatches, so the fault can be tied to the syscall it follows. */
    for (int i = 0; i < 16 && p < end; i++) {
        D3Ring entry;
        t_memset(&entry, 0, sizeof entry);
        if (!t_read_remote(target, (uint64_t)(uintptr_t)&g_ring[i], &entry, sizeof entry))
            continue;
        p = t_key(p, "r_kind", entry.kind);
        p = t_key(p, "r_extra", entry.extra);
        p = t_addr(p, "r_lr", bias, entry.lr);
        p = t_key(p, "r_x0", entry.x0);
    }
    /* The frame pointer chain, walking the tracee rather than our own copy. */
    for (int i = 0; i < 24 && p < end; i++) {
        uint64_t frame[2];
        if (!fp || (fp & 7u) || fp < 0x1000u)
            break;
        if (!t_read_remote(target, fp, frame, sizeof frame))
            break;
        p = t_key(p, "bt_sp", fp);
        p = t_addr(p, "bt_lr", bias, frame[1]);
        sp = fp + 16;
        fp = frame[0];
        if (fp && fp <= sp)
            break;
    }
    /* The words at the faulting stack pointer, so a corrupted frame is visible. */
    {
        uint64_t words[48];
        t_memset(words, 0, sizeof words);
        if (t_read_remote(target, sp & ~7u, words, sizeof words)) {
            for (int i = 0; i < 48 && p < end; i += 4) {
                p = t_str(p, "sp");
                p = t_dec(p, (uint64_t)i * 8u);
                *p++ = '+';
                for (int j = 0; j < 4; j++) {
                    *p++ = ' ';
                    p = t_hex(p, words[i + j]);
                }
                *p++ = 10;
            }
        } else {
            p = t_str(p, "sp read failed\n");
        }
    }
    t_pwrite(fd, TRACE_STATE_OFF + (index % 16u) * 0x4000u,
             g_trace_state, (size_t)(p - g_trace_state));
}

static void tracer_main(pid_t target, pid_t attach_tid) {
    D3PtRegs regs;
    D3Siginfo info;
    D3Iov local;
    long fd = t_open_trace();
    uint64_t seq = 0;
    uint64_t faults = 0;
    int attached = 0;
    int options = 0;
    if (fd < 0)
        raw_syscall6(RAW_SYS_EXIT_GROUP, 3, 0, 0, 0, 0, 0);
    for (int attempt = 0; attempt < 300 && !attached; attempt++) {
        if (raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_ATTACH, attach_tid, 0, 0, 0, 0) == 0)
            attached = 1;
        else
            t_sleep_ms(10);
    }
    if (!attached) {
        char *p = t_str(g_trace_state, "tag=d3trace attach=failed target=");
        p = t_dec(p, (uint64_t)target);
        *p++ = 10;
        t_pwrite(fd, TRACE_STATE_OFF, g_trace_state, (size_t)(p - g_trace_state));
        raw_syscall6(RAW_SYS_EXIT_GROUP, 4, 0, 0, 0, 0, 0);
    }
    for (;;) {
        char *p;
        int status = 0;
        long tid = raw_syscall4(RAW_SYS_WAIT4, -1, (long)(uintptr_t)&status, D3_WALL, 0);
        int stopped = (status & 0xff) == 0x7f;
        int sig = (status >> 8) & 0xff;
        int event = (status >> 16) & 0xffff;
        if (tid <= 0)
            break;
        if (!stopped) {
            p = t_str(g_trace_line, "e");
            p = t_dec(p, seq);
            p = t_str(p, " tid=");
            p = t_dec(p, (uint64_t)tid);
            p = t_str(p, " exited status=");
            p = t_hex(p, (uint64_t)status);
            *p++ = 10;
            t_pwrite(fd, TRACE_RING_OFF + (seq % TRACE_SLOTS) * TRACE_SLOT, g_trace_line,
                     (size_t)(p - g_trace_line));
            seq++;
            continue;
        }
        t_memset(&regs, 0, sizeof regs);
        local.base = (uint64_t)(uintptr_t)&regs;
        local.len = sizeof regs;
        if (raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_GETREGSET, tid, D3_NT_PRSTATUS,
                         (long)(uintptr_t)&local, 0, 0) != 0)
            t_memset(&regs, 0, sizeof regs);
        t_memset(&info, 0, sizeof info);
        raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_GETSIGINFO, tid, 0, (long)(uintptr_t)&info, 0, 0);
        if (!options) {
            raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_SETOPTIONS, tid, 0, D3_PTRACE_O_TRACECLONE, 0, 0);
            options = 1;
        }
        p = t_str(g_trace_line, "e");
        p = t_dec(p, seq);
        p = t_str(p, " tid=");
        p = t_dec(p, (uint64_t)tid);
        p = t_str(p, " sig=");
        p = t_dec(p, (uint64_t)sig);
        p = t_str(p, " ev=");
        p = t_dec(p, (uint64_t)event);
        p = t_str(p, " code=");
        p = t_dec(p, (uint64_t)(int64_t)info.code);
        p = t_str(p, " addr=");
        p = t_hex(p, info.addr);
        p = t_str(p, " pc=");
        p = t_hex(p, regs.pc);
        p = t_str(p, " lr=");
        p = t_hex(p, regs.regs[30]);
        p = t_str(p, " sp=");
        p = t_hex(p, regs.sp);
        p = t_str(p, " fp=");
        p = t_hex(p, regs.regs[29]);
        p = t_str(p, " x0=");
        p = t_hex(p, regs.regs[0]);
        p = t_str(p, " x1=");
        p = t_hex(p, regs.regs[1]);
        p = t_str(p, " x8=");
        p = t_hex(p, regs.regs[8]);
        p = t_str(p, " faults=");
        p = t_dec(p, faults);
        *p++ = 10;
        t_pwrite(fd, TRACE_RING_OFF + (seq % TRACE_SLOTS) * TRACE_SLOT, g_trace_line,
                 (size_t)(p - g_trace_line));
        if (sig == SIGSEGV || sig == SIGBUS || sig == SIGILL || sig == SIGABRT || sig == SIGFPE ||
            sig == SIGSYS || sig == SIGTRAP) {
            faults++;
            t_dump_maps(fd, target);
            t_state(fd, target, faults, (pid_t)tid, sig, event, &regs, &info);
        }
        /* Suppressing a stop would swallow a real signal, so only the stops the tracer
           itself caused are dropped. */
        {
            int deliver = (sig == SIGSTOP || event == D3_PTRACE_EVENT_CLONE) ? 0 : sig;
            raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_CONT, tid, 0, deliver, 0, 0);
        }
        seq++;
    }
    t_pwrite(fd, TRACE_RING_OFF + (seq % TRACE_SLOTS) * TRACE_SLOT, "tracee gone\n", 12);
    raw_syscall6(RAW_SYS_EXIT_GROUP, 0, 0, 0, 0, 0, 0);
}

static int trace_requested(void) {
    struct stat st;
    return stat(D3_DATA_ROOT "/trace", &st) == 0;
}

/* The child is the tracer, so the guest keeps running in the process that already
   has all the locks: it only has to tell the kernel the child may attach. */
static void start_tracer(void) {
    pid_t self = getpid();
    const pid_t attach_tid = gettid();
    long child = raw_syscall6(RAW_SYS_CLONE, D3_SIGCHLD, 0, 0, 0, 0, 0);
    if (child == 0) {
        tracer_main(self, attach_tid);
        raw_syscall6(RAW_SYS_EXIT_GROUP, 0, 0, 0, 0, 0, 0);
    }
    if (child > 0)
        raw_syscall6(RAW_SYS_PRCTL, D3_PR_SET_PTRACER, child, 0, 0, 0, 0);
}

static void *map_pages(size_t bytes, int prot) {
    void *ptr = mmap(0, bytes, prot, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (ptr == MAP_FAILED)
        fail("mmap %#zx prot %d errno %d", bytes, prot, errno);
    return ptr;
}

static uint64_t align_up_guest(uint64_t value, uint64_t alignment) {
    return (value + alignment - 1) & ~(alignment - 1);
}

static void read_guest(int fd, void *buffer, size_t size, off_t offset) {
    unsigned char *cursor = buffer;
    while (size) {
        ssize_t count = pread(fd, cursor, size, offset);
        if (count <= 0)
            fail("guest read offset=%" PRId64 " size=%zu errno=%d", (int64_t)offset, size, errno);
        cursor += count;
        offset += count;
        size -= (size_t)count;
    }
}

static int guest_prot(uint32_t flags) {
    int prot = 0;
    if (flags & PF_R)
        prot |= PROT_READ;
    if (flags & PF_W)
        prot |= PROT_WRITE;
    if (flags & PF_X)
        prot |= PROT_EXEC;
    return prot;
}

static void protect_guest_segment(uint64_t base, const Elf64_Phdr *ph) {
    uint64_t start = base + ph->p_vaddr;
    uint64_t end = align_up_guest(start + ph->p_memsz, g_os_page);
    if (!(ph->p_flags & PF_W) || !(ph->p_flags & PF_X)) {
        if (mprotect((void *)(uintptr_t)start, (size_t)(end - start), guest_prot(ph->p_flags)) != 0)
            fail("guest mprotect %#" PRIx64 " size=%" PRIx64 " errno=%d", start, end - start, errno);
        return;
    }
    uint64_t text_end = 0;
    if (ph->p_vaddr == D3_SDK_BASE)
        text_end = base + D3_SDK_TEXT_END;
    else if (ph->p_vaddr == D3_MAIN_BASE)
        text_end = base + D3_MAIN_TEXT_END;
    else
        fail("unexpected writable executable segment %#" PRIx64, (uint64_t)ph->p_vaddr);
    uint64_t rx_end = align_up_guest(text_end, g_os_page);
    if (rx_end > start && mprotect((void *)(uintptr_t)start, (size_t)(rx_end - start), PROT_READ | PROT_EXEC) != 0)
        fail("guest text mprotect errno %d", errno);
    if (end > rx_end && mprotect((void *)(uintptr_t)rx_end, (size_t)(end - rx_end), PROT_READ | PROT_WRITE) != 0)
        fail("guest data mprotect errno %d", errno);
}

/* -------------------------------------------------------------------------
   SDK symbol hooks.

   The guest is a stripped merge of rtld + main + sdk: no .symtab, no usable
   .dynsym.  The names are recoverable from the copy of the title the user owns
   (the program NCA's exefs), so reference/extract/exefs_update/sdk.symbols.json
   holds 25142 nnSdk exports as offsets from the sdk module base.  The merge
   places that module at vaddr 0x10000, verified byte-for-byte against the
   image, so a symbol's guest address is 0x10000 + its recorded offset.

   A hook rewrites the entry with

       ldr x16, #8     0x58000050
       br  x16         0xd61f0200
       .quad host_fn

   which leaves x0..x7 (the guest's arguments) and x30 (its return address)
   untouched, so the host body runs with the guest's own ABI and returns
   straight to the guest caller.  nnsdk's nn::time entry points are replaced
   with host clocks, which is what keeps the SDK from ever opening the time
   service -- the GetSharedMemory path that aborted boot with 0x2a2. */

typedef struct {
    uint64_t vaddr;
    void *target;
    const char *name;
} GuestHook;

static uint64_t hook_time_initialize(void) {
    return 0;
}

static uint64_t hook_time_is_initialized(void) {
    return 1;
}

/* nn::socket::Initialize opens bsd:u and maps its buffer shared memory; with no
   network service behind the host the SDK's own path only reaches an assertion.
   The title is single player, so a successful no-op is enough to keep booting. */
static uint64_t hook_success(void) {
    return 0;
}

/* nn::fs sizes the romfs cache from the card and then asserts when the answer
   does not fit; the host owns the romfs, so the guest just gets a fixed budget. */
static uint64_t hook_fs_rom_cache_size(uint64_t out) {
    if (out)
        *(uint64_t *)(uintptr_t)out = 0x2000000ull;
    return 0;
}

static int64_t hook_time_now(void) {
    return (int64_t)time(NULL);
}

static uint64_t hook_time_get_current_time(uint64_t out) {
    if (out)
        *(int64_t *)(uintptr_t)out = (int64_t)time(NULL);
    return 0;
}

/* CalendarTime is {s16 year; s8 month, day, hour, minute, second, pad} and
   CalendarAdditionalInfo is {u32 wday; u32 yday; char tzname[8]; u32 dst;
   s32 utc offset}, per the public Horizon ABI. */
static uint64_t hook_time_to_calendar(uint64_t calendar_out, uint64_t info_out, uint64_t posix) {
    struct tm tm;
    time_t stamp = posix ? (time_t)*(const int64_t *)(uintptr_t)posix : time(NULL);
    if (localtime_r(&stamp, &tm) == NULL)
        return 1;
    if (calendar_out) {
        int8_t *calendar = (int8_t *)(uintptr_t)calendar_out;
        int16_t year = (int16_t)(tm.tm_year + 1900);
        memcpy(calendar, &year, sizeof year);
        calendar[2] = (int8_t)(tm.tm_mon + 1);
        calendar[3] = (int8_t)tm.tm_mday;
        calendar[4] = (int8_t)tm.tm_hour;
        calendar[5] = (int8_t)tm.tm_min;
        calendar[6] = (int8_t)tm.tm_sec;
        calendar[7] = 0;
    }
    if (info_out) {
        uint8_t *info = (uint8_t *)(uintptr_t)info_out;
        const char *zone = tm.tm_zone ? tm.tm_zone : "UTC";
        memset(info, 0, 0x18);
        memcpy(info, &(uint32_t){(uint32_t)tm.tm_wday}, sizeof(uint32_t));
        memcpy(info + 4, &(uint32_t){(uint32_t)tm.tm_yday}, sizeof(uint32_t));
        for (int i = 0; i < 7 && zone[i]; i++)
            info[8 + i] = (uint8_t)zone[i];
        memcpy(info + 0x10, &(uint32_t){tm.tm_isdst > 0}, sizeof(uint32_t));
        memcpy(info + 0x14, &(int32_t){(int32_t)tm.tm_gmtoff}, sizeof(int32_t));
    }
    return 0;
}

/* nn::fs's public API is a thin wrapper over the fssrv IPC.  Replacing it here
   avoids modelling IFile/IDirectory objects at all: the arguments are ordinary
   pointers, so the host can read and write the guest's buffers directly.
   Paths like "data:/CPKs/Common.cpk" resolve under the staged game data. */

#define D3_FS_HANDLES 256

typedef struct {
    int used;
    int fd;
    int64_t size;
} FsHandle;

static FsHandle g_fs_handles[D3_FS_HANDLES];
static pthread_mutex_t g_fs_handle_mutex = PTHREAD_MUTEX_INITIALIZER;

/* The staged game data is readable but not writable by the app, so anything the
   title creates has to live in the app's own storage; reads fall back to the
   shared copy. */
static const char *const g_guest_data_roots[] = {
    D3_CONTENT_ROOT,
};

static pthread_mutex_t g_addon_mount_mutex = PTHREAD_MUTEX_INITIALIZER;
static struct { char name[16]; unsigned index; } g_addon_mounts[32];
static uint64_t g_unmount_trampoline;
static uint32_t g_addon_mount_logs;
extern void d3_call_guest_one(uint64_t function, uint64_t argument, uint64_t thread_tp);

static uint64_t hook_fs_unmount(uint64_t name_pointer) {
    const char *name = (const char *)(uintptr_t)name_pointer;
    if (!name) return 0;
    pthread_mutex_lock(&g_addon_mount_mutex);
    for (size_t i = 0; i < 32; ++i) {
        if (!g_addon_mounts[i].name[0] || strcmp(g_addon_mounts[i].name, name)) continue;
        g_addon_mounts[i].name[0] = 0;
        pthread_mutex_unlock(&g_addon_mount_mutex);
        if (__atomic_fetch_add(&g_addon_mount_logs, 1, __ATOMIC_RELAXED) < 24)
            info("fs: Unmount addon %s", name);
        return 0;
    }
    pthread_mutex_unlock(&g_addon_mount_mutex);
    if (g_unmount_trampoline) d3_call_guest_one(g_unmount_trampoline, name_pointer, hook_guest_tp());
    return 0;
}

static uint64_t hook_fs_addon_cache_size(uint64_t out, uint64_t index) {
    char root[512];
    if (!out || index > 0xfff || !d3_content_addon_root((unsigned)index, root, sizeof root)) return 0x202u;
    *(uint64_t *)(uintptr_t)out = 4096;
    return 0;
}

static uint64_t hook_fs_mount_addon(uint64_t name_pointer, uint64_t index,
                                  uint64_t cache, uint64_t cache_size) {
    const char *name = (const char *)(uintptr_t)name_pointer;
    char root[512];
    if (!name || !*name || strlen(name) >= sizeof g_addon_mounts[0].name ||
        strchr(name, ':') || strchr(name, '/') || strchr(name, '\\') ||
        !cache || cache_size < 4096 || index > 0xfff || !d3_content_addon_root((unsigned)index, root, sizeof root))
        return 0x202u;
    pthread_mutex_lock(&g_addon_mount_mutex);
    for (size_t i = 0; i < 32; ++i) {
        if (g_addon_mounts[i].name[0] && strcmp(g_addon_mounts[i].name, name)) continue;
        snprintf(g_addon_mounts[i].name, sizeof g_addon_mounts[i].name, "%s", name);
        g_addon_mounts[i].index = (unsigned)index;
        pthread_mutex_unlock(&g_addon_mount_mutex);
        if (__atomic_fetch_add(&g_addon_mount_logs, 1, __ATOMIC_RELAXED) < 24)
            info("fs: MountAddOnContent %s index=%llu root=%s", name, (unsigned long long)index, root);
        return 0;
    }
    pthread_mutex_unlock(&g_addon_mount_mutex);
    return 0x2a02u;
}

#define D3_GUEST_WRITE_ROOT D3_PRIVATE_ROOT "/files/romfs"

static FsHandle *fs_handle_of(uint64_t handle) {
    if (handle < 1 || handle > D3_FS_HANDLES)
        return 0;
    FsHandle *slot = &g_fs_handles[handle - 1];
    return slot->used ? slot : 0;
}

/* "data:/CPKs/x.cpk" -> "CPKs/x.cpk"; mount prefixes are not part of the
   on-host layout. */
static const char *guest_data_name(const char *path) {
    const char *name = path;
    if (strncmp(name, "data:", 5) == 0)
        name += 5;
    while (*name == '/')
        name++;
    return name;
}

static void make_parents(const char *host) {
    char dir[512];
    snprintf(dir, sizeof dir, "%s", host);
    char *slash = strrchr(dir, '/');
    if (slash == 0)
        return;
    *slash = 0;
    for (char *walk = dir + 1; *walk; walk++) {
        if (*walk == '/') {
            *walk = 0;
            mkdir(dir, 0777);
            *walk = '/';
        }
    }
    mkdir(dir, 0777);
}

static int guest_data_host(const char *path, char *out, size_t size, int create) {
    const char *colon = strchr(path, ':');
    if (colon && strncmp(path, "data:", 5) && strncmp(path, "save", 4)) {
        char root[512] = {0};
        pthread_mutex_lock(&g_addon_mount_mutex);
        for (size_t i = 0; i < 32; ++i) {
            const size_t length = strlen(g_addon_mounts[i].name);
            if (length && (size_t)(colon - path) == length && !memcmp(path, g_addon_mounts[i].name, length)) {
                if (!d3_content_addon_root(g_addon_mounts[i].index, root, sizeof root)) root[0] = 0;
                break;
            }
        }
        pthread_mutex_unlock(&g_addon_mount_mutex);
        if (!root[0] || create) return -1;
        const char *name = colon + 1;
        while (*name == '/') ++name;
        if (strstr(name, "..") || strchr(name, ':') || strchr(name, '\\')) return -1;
        const int length = snprintf(out, size, "%s/%s", root, name);
        return length >= 0 && (size_t)length < size ? 0 : -1;
    }
    if (!strncmp(path, "save", 4)) {
        const char *colon = path + 4;
        while (*colon >= '0' && *colon <= '9') colon++;
        if (*colon == ':') {
            const char *name = colon + 1;
            while (*name == '/') name++;
            if (strstr(name, "..") || strchr(name, ':') || strchr(name, '\\')) return -1;
            const int length = snprintf(out, size, "%s/%s", D3_LOCAL_SAVE_ROOT, name);
            return length >= 0 && (size_t)length < size ? 0 : -1;
        }
    }
    const char *name = guest_data_name(path);
    if (*name == 0)
        return -1;
    snprintf(out, size, "%s/%s", create ? D3_GUEST_WRITE_ROOT : g_guest_data_roots[0], name);
    for (char *separator = out; *separator; separator++) {
        if (*separator == '\\')
            *separator = '/';
    }
    if (create)
        make_parents(out);
    if (create) {
        char dir[512];
        snprintf(dir, sizeof dir, "%s", out);
        char *slash = strrchr(dir, '/');
        if (slash != 0) {
            *slash = 0;
            for (char *walk = dir + 1; *walk; walk++) {
                if (*walk == '/') {
                    *walk = 0;
                    mkdir(dir, 0777);
                    *walk = '/';
                }
            }
            mkdir(dir, 0777);
        }
    }
    return 0;
}

static int fs_open_host_mode(const char *path, int writable) {
    char host[512];
    int fd = -1;
    /* Writable opens go to the app's own tree first, reads fall back to the
       staged read-only copy. */
    if (writable && guest_data_host(path, host, sizeof host, 1) == 0) {
        fd = open(host, O_RDWR | O_CREAT, 0666);
        if (fd >= 0)
            info("fs: opened(rw) %s", host);
    }
    if (fd < 0 && guest_data_host(path, host, sizeof host, 0) == 0)
        fd = open(host, O_RDONLY);
    if (fd < 0) {
        info("fs: open %s failed errno %d", path, errno);
        return -1;
    }
    struct stat statbuf;
    if (fstat(fd, &statbuf) != 0 || !S_ISREG(statbuf.st_mode)) {
        close(fd);
        return -1;
    }
    pthread_mutex_lock(&g_fs_handle_mutex);
    for (int index = 0; index < D3_FS_HANDLES; index++) {
        if (g_fs_handles[index].used)
            continue;
        g_fs_handles[index].used = 1;
        g_fs_handles[index].fd = fd;
        g_fs_handles[index].size = (int64_t)statbuf.st_size;
        pthread_mutex_unlock(&g_fs_handle_mutex);
        info("fs: opened %s (%lld bytes) as handle %d", host, (long long)statbuf.st_size, index + 1);
        return index + 1;
    }
    pthread_mutex_unlock(&g_fs_handle_mutex);
    close(fd);
    return -1;
}

#define D3_FS_NOT_FOUND 0x202u

static uint64_t hook_fs_open_file(uint64_t out, uint64_t path, uint64_t mode) {
    info("fs: OpenFile %s mode=%#" PRIx64, path ? (const char *)(uintptr_t)path : "(null)", mode);
    if (path && strstr((const char *)(uintptr_t)path, "CrashInfo")) {
        static int logs;
        if (logs < 6) {
            logs++;
            info("fs: CrashInfo open caller=%#" PRIx64 " (%s+%#" PRIx64 ")", g_hook_tls.guest_lr,
                 module_of(g_hook_tls.guest_lr),
                 g_hook_tls.guest_lr >= g_bias ? g_hook_tls.guest_lr - g_bias : 0);
        }
    }
    /* mode bit 0 is read; the title opens with 1 and only creates through
       nn::fs::CreateFile, so a plain open must never create. */
    int handle = path ? fs_open_host_mode((const char *)(uintptr_t)path, (mode & 2) != 0) : -1;
    if (handle < 0)
        return D3_FS_NOT_FOUND;
    if (out)
        *(int64_t *)(uintptr_t)out = handle;
    return 0;
}

static uint64_t hook_fs_close_file(uint64_t handle) {
    pthread_mutex_lock(&g_fs_handle_mutex);
    FsHandle *slot = fs_handle_of(handle);
    if (slot == 0) {
        pthread_mutex_unlock(&g_fs_handle_mutex);
        return D3_FS_NOT_FOUND;
    }
    close(slot->fd);
    slot->used = 0;
    pthread_mutex_unlock(&g_fs_handle_mutex);
    return 0;
}

static int64_t fs_read(uint64_t handle, int64_t offset, uint64_t buffer, uint64_t size) {
    FsHandle *slot = fs_handle_of(handle);
    static uint32_t reads_logged;
    const int log_read = __atomic_fetch_add(&reads_logged, 1, __ATOMIC_RELAXED) < 128;
    if (log_read)
        info("fs: read begin h=%llu off=%lld buf=%#" PRIx64 " size=%llu", (unsigned long long)handle,
             (long long)offset, buffer, (unsigned long long)size);
    if (slot == 0 || buffer == 0) {
        info("fs: read rejected");
        return -1;
    }
    if (offset < 0)
        offset = 0;
    if (offset >= slot->size) {
        info("fs: read past end (%lld >= %lld)", (long long)offset, (long long)slot->size);
        return 0;
    }
    /* Callers compute the length as fileSize - offset; an offset past the end
       underflows into a huge size, which only ever means "nothing left". */
    if (size == 0 || (int64_t)size < 0 || size > (uint64_t)(slot->size - offset)) {
        size = (uint64_t)(slot->size - offset);
        info("fs: read clamped to %llu", (unsigned long long)size);
    }
#ifdef D3_WITH_GPU
    d3_gpu_begin_cpu_write(buffer, size);
#endif
    ssize_t got = pread(slot->fd, (void *)(uintptr_t)buffer, (size_t)size, (off_t)offset);
#ifdef D3_WITH_GPU
    d3_gpu_end_cpu_write();
#endif
    if (log_read || got < 0)
        info("fs: read end got=%lld", (long long)got);
    return got < 0 ? -1 : (int64_t)got;
}

static uint64_t hook_fs_read_file(uint64_t handle, uint64_t offset, uint64_t buffer, uint64_t size) {
    return fs_read(handle, (int64_t)offset, buffer, size) < 0 ? D3_FS_NOT_FOUND : 0;
}

static uint64_t hook_fs_read_file_count(uint64_t out, uint64_t handle, uint64_t offset, uint64_t buffer,
                                        uint64_t size) {
    int64_t got = fs_read(handle, (int64_t)offset, buffer, size);
    if (got < 0)
        return D3_FS_NOT_FOUND;
    if (out)
        *(uint64_t *)(uintptr_t)out = (uint64_t)got;
    return 0;
}

static uint64_t hook_fs_get_file_size(uint64_t out, uint64_t handle) {
    FsHandle *slot = fs_handle_of(handle);
    if (slot == 0)
        return D3_FS_NOT_FOUND;
    if (out)
        *(int64_t *)(uintptr_t)out = slot->size;
    return 0;
}

static uint64_t hook_fs_create_file(uint64_t path, uint64_t size, uint64_t mode) {
    (void)mode;
    char host[512];
    if (path == 0 || guest_data_host((const char *)(uintptr_t)path, host, sizeof host, 1) != 0)
        return D3_FS_NOT_FOUND;
    int fd = open(host, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) {
        info("fs: create %s failed errno %d", host, errno);
        return errno == EEXIST ? 0x402u : D3_FS_NOT_FOUND;
    }
    if ((int64_t)size > 0 && ftruncate(fd, (off_t)(int64_t)size) != 0)
        info("fs: truncate %s errno %d", host, errno);
    close(fd);
    info("fs: created %s (%lld bytes)", host, (long long)size);
    return 0;
}

static uint64_t hook_fs_write_file(uint64_t handle, uint64_t offset, uint64_t buffer, uint64_t size,
                                   uint64_t option) {
    (void)option;
    FsHandle *slot = fs_handle_of(handle);
    if (slot == 0 || buffer == 0 || size > (1ull << 30))
        return D3_FS_NOT_FOUND;
    ssize_t put = pwrite(slot->fd, (const void *)(uintptr_t)buffer, (size_t)size, (off_t)(int64_t)offset);
    info("fs: write h=%llu off=%lld size=%llu -> %lld", (unsigned long long)handle, (long long)offset,
         (unsigned long long)size, (long long)put);
    if (put < 0)
        return D3_FS_NOT_FOUND;
    if ((int64_t)(offset + size) > slot->size)
        slot->size = (int64_t)(offset + size);
    return 0;
}

static uint64_t hook_fs_flush_file(uint64_t handle) {
    FsHandle *slot = fs_handle_of(handle);
    if (slot != 0)
        fsync(slot->fd);
    return 0;
}

static uint64_t hook_fs_set_file_size(uint64_t handle, uint64_t size) {
    FsHandle *slot = fs_handle_of(handle);
    if (slot == 0)
        return D3_FS_NOT_FOUND;
    if (ftruncate(slot->fd, (off_t)(int64_t)size) != 0)
        return D3_FS_NOT_FOUND;
    slot->size = (int64_t)size;
    info("fs: SetFileSize h=%llu -> %llu", (unsigned long long)handle, (unsigned long long)size);
    return 0;
}


/* Diagnostic: the guest currently dies through std::terminate.  __cxa_throw is
   called with (object, std::type_info*, destructor) and its guest return
   address is the throw site, which is exactly what is missing from the crash
   reports.  The hook logs and stops, because a throw must not return. */
static uint64_t hook_cxa_throw(uint64_t object, uint64_t type_info, uint64_t destructor) {
    const uint64_t site = g_hook_tls.guest_lr;
    const char *name = "?";
    if (type_info) {
        uint64_t name_ptr = *(const uint64_t *)(uintptr_t)(type_info + 8);
        if (name_ptr)
            name = (const char *)(uintptr_t)name_ptr;
    }
    info("__cxa_throw type=%s thrower=%#" PRIx64 " (%s+%#" PRIx64 ") obj=%#" PRIx64
         " dtor=%#" PRIx64,
         name, site, module_of(site), site >= g_bias ? site - g_bias : 0, object, destructor);
    abort();
    return 0;
}

static uint64_t hook_terminate(void) {
    const uint64_t site = g_hook_tls.guest_lr;
    info("std::terminate caller=%#" PRIx64 " (%s+%#" PRIx64 ")", site, module_of(site),
         site >= g_bias ? site - g_bias : 0);
    abort();
    return 0;
}

static uint64_t hook_raise_exception(uint64_t exception) {
    const uint64_t site = g_hook_tls.guest_lr;
    info("_Unwind_RaiseException exception=%#" PRIx64 " caller=%#" PRIx64 " (%s+%#" PRIx64 ")",
         exception, site, module_of(site), site >= g_bias ? site - g_bias : 0);
    abort();
    return 0;
}

static void log_cstr(const char *label, uint64_t ptr) {
    if (!ptr) {
        info("%s=(null)", label);
        return;
    }
    unsigned char raw[16] = {0};
    char text[160] = {0};
    if (!safe_read(ptr, raw, sizeof raw)) {
        info("%s ptr=%#" PRIx64 " unreadable", label, ptr);
        return;
    }
    for (int i = 0; i < 120; ++i) {
        unsigned char c = raw[0];
        if (i < (int)sizeof raw)
            c = raw[i];
        else if (!safe_read(ptr + (uint64_t)i, &c, 1))
            break;
        if (c < 32 || c >= 127)
            break;
        text[i] = (char)c;
    }
    if (text[0]) {
        info("%s=[%s] ptr=%#" PRIx64, label, text, ptr);
        return;
    }
    info("%s is not text: ptr=%#" PRIx64 " words=%08x %08x %08x %08x", label, ptr,
         (unsigned)raw[0] | ((unsigned)raw[1] << 8) | ((unsigned)raw[2] << 16) |
             ((unsigned)raw[3] << 24),
         (unsigned)raw[4] | ((unsigned)raw[5] << 8) | ((unsigned)raw[6] << 16) |
             ((unsigned)raw[7] << 24),
         (unsigned)raw[8] | ((unsigned)raw[9] << 8) | ((unsigned)raw[10] << 16) |
             ((unsigned)raw[11] << 24),
         (unsigned)raw[12] | ((unsigned)raw[13] << 8) | ((unsigned)raw[14] << 16) |
             ((unsigned)raw[15] << 24));
}

/* The trampoline records the guest's return address, so an abort names the guest
   call site instead of the hook stub. */
static void log_hook_region(const char *what) {
    const uint64_t tp = g_hook_tls.guest_tp;
    const uint64_t tlr = tp + GUEST_TLR_OFFSET;
    const uint64_t thread = tlr ? *(const uint64_t *)(uintptr_t)(tlr + 0x1f8) : 0;
    const uint32_t id = thread ? *(const uint32_t *)(uintptr_t)(thread + 0x1b0) : 0;
    uint32_t word = 0;
    if (g_bias)
        (void)safe_read(g_bias + 0xcd9b4cu, &word, sizeof word);
    info("%s tid=%ld tp=%#" PRIx64 " thread=%#" PRIx64 " id=%#x applet_mutex=%#x", what,
         (long)syscall(SYS_gettid), tp, thread, (unsigned)id, word);
    const int count = __atomic_load_n(&g_tp_map_count, __ATOMIC_ACQUIRE);
    for (int index = 0; index < count; index++)
        info("tp map %d: tp=%#" PRIx64 " tls=%#" PRIx64, index, g_tp_map[index].tp,
             g_tp_map[index].tls);
}

static void log_hook_site(const char *what) {
    const uint64_t site = g_hook_tls.guest_lr;
    info("%s caller=%#" PRIx64 " (%s+%#" PRIx64 ")", what, site, module_of(site),
         site >= g_bias ? site - g_bias : (uint64_t)0);
}

/* The innermost frame only names the assert helper; the caller chain that got
   there is still on the guest stack, so keep the return addresses that point into
   the image and name them by module. */
static void log_guest_stack(uint64_t sp, int words) {
    int shown = 0;
    for (int index = 0; index < words && shown < 24; index++) {
        uint64_t word = 0;
        if (!safe_read(sp + (uint64_t)index * 8u, &word, sizeof word))
            break;
        const char *module = module_of(word);
        if (module[0] == 'h' && module[1] == 'o')
            continue;
        const uint64_t off = word - g_bias;
        const uint64_t rel = off < 0x1000000u ? off : off - 0x1000000u;
        info("  stack[%d] %s+%#" PRIx64, index, module, rel);
        shown++;
    }
}

/* nn::os::SdkRecursiveMutexType::Unlock = assert(IsLockedByCurrentThread) then
   --count, and Leave() when the count reaches zero.  The assert is what keeps
   firing while the title hands locks between threads, so the decrement and the
   release happen here instead.  Layout: word at +0, recursion count at +4. */
static uint64_t hook_recursive_mutex_unlock(uint64_t self) {
    uint32_t count = 0;
    uint32_t word = 0;
    if (!self || !safe_read(self + 4, &count, sizeof count))
        return 0;
    (void)safe_read(self, &word, sizeof word);
    const uint32_t id = guest_thread_id(hook_guest_tp());
    static int logs;
    if (logs < 16) {
        logs++;
        const uint64_t site = g_hook_tls.guest_lr;
        info("SdkRecursiveMutexType::Unlock self=%p count=%u word=%#x my_id=%#x caller=%s+%#" PRIx64,
             (void *)(uintptr_t)self, count, word, id, module_of(site), site - g_bias);
    }
    if (count > 1) {
        const uint32_t next = count - 1;
        *(uint32_t *)(uintptr_t)(self + 4) = next;
        return 0;
    }
    *(uint32_t *)(uintptr_t)(self + 4) = 0;
    (void)d3_sync_unlock((uint32_t *)(uintptr_t)self, id);
    return 0;
}

/* nn::os TLS slots.  Storing them in the guest's thread object
   ([tpidrro_el0+0x1f8]+0x80+slot*8) looked right, but the title re-points that
   word at different thread objects while it runs, so a slot set on one object was
   read back from another as 0 -- and the engine then dereferenced the NULL it got
   from GetTlsValue.  Every TLS access goes through these two SDK functions, so the
   table can live here, keyed by the calling thread's own region. */
#define MAX_TLS_SLOTS 256
static struct {
    uint64_t region;
    uint32_t slot;
    uint64_t value;
} g_tls_slots[MAX_TLS_SLOTS];
static int g_tls_slot_count;
static pthread_mutex_t g_tls_slot_mutex = PTHREAD_MUTEX_INITIALIZER;

static int tls_slot_find(uint64_t region, uint32_t slot) {
    const int count = __atomic_load_n(&g_tls_slot_count, __ATOMIC_ACQUIRE);
    for (int index = 0; index < count; index++) {
        if (g_tls_slots[index].region == region && g_tls_slots[index].slot == slot)
            return index;
    }
    return -1;
}

static uint64_t hook_tls_set(uint64_t slot, uint64_t value) {
    const uint64_t region = this_guest_tls();
    if (slot >= 64 || !region)
        return 0;
    pthread_mutex_lock(&g_tls_slot_mutex);
    int index = tls_slot_find(region, (uint32_t)slot);
    if (index < 0 && g_tls_slot_count < MAX_TLS_SLOTS) {
        index = g_tls_slot_count++;
        g_tls_slots[index].region = region;
        g_tls_slots[index].slot = (uint32_t)slot;
    }
    if (index >= 0)
        g_tls_slots[index].value = value;
    pthread_mutex_unlock(&g_tls_slot_mutex);
    static int set_logs;
    if (set_logs < 16) {
        set_logs++;
        info("tls: set slot=%u value=%#" PRIx64 " region=%#" PRIx64 " tid=%ld", (unsigned)slot,
             value, region, (long)syscall(SYS_gettid));
    }
    return 0;
}

static uint64_t hook_tls_get(uint64_t slot) {
    const uint64_t region = this_guest_tls();
    uint64_t value = 0;
    pthread_mutex_lock(&g_tls_slot_mutex);
    const int index = tls_slot_find(region, (uint32_t)slot);
    if (index >= 0)
        value = g_tls_slots[index].value;
    pthread_mutex_unlock(&g_tls_slot_mutex);
    static int get_logs;
    if (!value && get_logs < 16) {
        get_logs++;
        info("tls: get slot=%u -> 0 (region=%#" PRIx64 " tid=%ld)", (unsigned)slot, region,
             (long)syscall(SYS_gettid));
    }
    return value;
}

/* nn::os::detail::InternalCriticalSectionImplByHorizon::Enter.  The SDK version
   asserts \"this == NULL\" and compares the lock word against the thread id read
   from tpidrro_el0; both are fragile here (the title re-points its thread pointer
   and some engine objects are still uninitialised while the GPU path runs).  The
   host implements the same word protocol it already uses for svcArbitrateLock. */
static uint64_t hook_critical_enter(uint64_t self) {
    if (!self) {
        static int null_logs;
        if (null_logs < 8) {
            null_logs++;
            info("Enter(NULL) tolerated (engine critical section not initialised)");
        }
        return 0;
    }
    const uint32_t id = guest_thread_id(hook_guest_tp());
    uint32_t *mutex = (uint32_t *)(uintptr_t)self;
    uint32_t word = __atomic_load_n(mutex, __ATOMIC_ACQUIRE);
    for (;;) {
        if ((word & ~D3_SYNC_WAIT_MASK) == id)
            return 0;
        const uint32_t desired = word ? word | D3_SYNC_WAIT_MASK : id;
        if (!__atomic_compare_exchange_n(mutex, &word, desired, 0,
                                         __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
            continue;
        if (word == 0)
            return 0;
        const uint32_t result = d3_sync_lock(word & ~D3_SYNC_WAIT_MASK, mutex, id);
        if (result != 0)
            fail("critical section %p wait failed: %#x owner=%#x tag=%#x word=%#x owner-kind=%d",
                 (void *)mutex, result, word & ~D3_SYNC_WAIT_MASK, id,
                 __atomic_load_n(mutex, __ATOMIC_ACQUIRE), d3_handle_kind(word & ~D3_SYNC_WAIT_MASK));
        word = __atomic_load_n(mutex, __ATOMIC_ACQUIRE);
    }
}

/* The engine bails out through nn::os::ExitProcess when an initialisation step
   fails: the process then dies with no signal and no message.  Report the caller
   and stop right there so the exit site is in the log. */
static uint64_t hook_exit_process(uint64_t code) {
    log_hook_site("ExitProcess");
    log_guest_stack((uint64_t)(uintptr_t)__builtin_frame_address(0) + 0x200u, 512);
    info("ExitProcess code=%#" PRIx64, code);
    abort();
    return 0;
}

static uint64_t hook_abort_impl(uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e,
                                uint64_t f) {
    log_hook_site("AbortImpl");
    log_hook_region("abort region");
    log_guest_stack((uint64_t)(uintptr_t)__builtin_frame_address(0) + 0x200u, 768);
    log_cstr("abort arg0", a);
    log_cstr("abort arg1", b);
    log_cstr("abort arg2", c);
    log_cstr("abort arg3", d);
    /* The failing nn::Result travels as a pointer in the operand slot (the SDK
       calls the (f, f, f, i, r, v) variant for these checks), so read it out:
       "this == NULL" alone never says which call returned what. */
    uint32_t operand = 0;
    if (e && safe_read(e, &operand, sizeof operand))
        info("abort operand [%#" PRIx64 "] = %#x", e, operand);
    else
        info("abort operand arg4=%#" PRIx64 " arg5=%#" PRIx64, e, f);
    /* nn::account::Initialize keeps its state in statics: the init count and its
       mutex live at image +0xbf65cc / +0xbf65d0, and the ObjectHolder it fills is
       at +0xc520b0 (the client object it acquired lands at +8).  The failing
       nn::Result travels in whichever of sp, sp+8, sp+0x18 the operand pointer
       names, so the words around it say which of the three checks aborted. */
    if (g_bias) {
        uint32_t init_count = 0;
        uint64_t holder[2] = {0, 0};
        (void)safe_read(g_bias + 0xbf65ccu, &init_count, sizeof init_count);
        (void)safe_read(g_bias + 0xc520b0u, holder, sizeof holder);
        info("abort account init_count=%#x holder=%#" PRIx64 " object=%#" PRIx64
             " last_reply=%#x", init_count, holder[0], holder[1], d3_service_last_result());
        if (holder[1]) {
            uint64_t object[8] = {0};
            if (safe_read(holder[1], object, sizeof object))
                info("abort account object %#" PRIx64 ": %#" PRIx64 " %#" PRIx64 " %#" PRIx64
                     " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64,
                     holder[1], object[0], object[1], object[2], object[3], object[4], object[5],
                     object[6], object[7]);
            else
                info("abort account object %#" PRIx64 " unreadable", holder[1]);
        }
        /* The hid applet resource path (sdk+0x250300) calls a second proxy
           through this global right after CreateAppletResource; when that call
           fails the abort lands here, so the global and its object name the
           proxy and the session handle it carries. */
        uint64_t proxy = 0;
        if (safe_read(g_bias + 0xc9bba8u, &proxy, sizeof proxy) && proxy) {
            uint64_t object[16] = {0};
            if (safe_read(proxy, object, sizeof object)) {
                info("abort hid global %#" PRIx64 " -> %#" PRIx64 " vtbl=%#" PRIx64,
                     g_bias + 0xc9bba8u, proxy, object[0]);
                info("abort hid object %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#"
                     PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64,
                     object[0], object[1], object[2], object[3], object[4], object[5], object[6],
                     object[7]);
                uint64_t slots[8] = {0};
                if (object[0] >= g_bias && safe_read(object[0], slots, sizeof slots))
                    info("abort hid vtbl %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64
                         " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64,
                         slots[0], slots[1], slots[2], slots[3], slots[4], slots[5], slots[6],
                         slots[7]);
            } else {
                info("abort hid global %#" PRIx64 " -> %#" PRIx64 " unreadable",
                     g_bias + 0xc9bba8u, proxy);
            }
        } else {
            info("abort hid global %#" PRIx64 " -> %#" PRIx64, g_bias + 0xc9bba8u, proxy);
        }
        if (e >= 0x40) {
            uint64_t words[12] = {0};
            if (safe_read(e - 0x20, words, sizeof words))
                info("abort words %#" PRIx64 ": %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64
                     " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64
                     " %#" PRIx64 " %#" PRIx64,
                     e - 0x20, words[0], words[1], words[2], words[3], words[4], words[5], words[6],
                     words[7], words[8], words[9], words[10], words[11]);
            else
                info("abort words %#" PRIx64 " unreadable", e - 0x20);
        }
    }
    abort();
    return 0;
}

static uint64_t hook_assert_failure(uint64_t type, uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    info("OnAssertionFailure type=%" PRIu64, type);
    log_hook_site("OnAssertionFailure");
    log_cstr("assert arg1", a);
    log_cstr("assert arg2", b);
    log_cstr("assert arg3", c);
    log_cstr("assert arg4", d);
    abort();
    return 0;
}

/* Horizon's svcArbitrateUnlock never checks ownership: it releases the lock word
   and hands it to the first waiter.  Nintendo's SDK adds its own defensive check
   (nn::os::SdkMutexType::Unlock aborts when the word's owner is not this thread's
   id, which happens when the applet thread and the boot thread both take the
   SDK's static applet mutex).  Replacing that wrapper with the kernel behaviour
   keeps the lock state consistent instead of aborting. */
static void guest_call(uint64_t fn, uint64_t arg0, uint64_t arg1);
static void guest_call_with_tp(uint64_t fn, uint64_t arg0, uint64_t arg1, uint64_t guest_tp);

static uint64_t hook_mutex_unlock(uint64_t mutex) {
    /* Run the SDK's own Leave so its thread-local bookkeeping stays in step; only
       the ownership assert is skipped.  The call must keep the thread pointer the
       guest is running on: Leave reads the mutex owner id out of
       [tpidrro_el0 + 0x1f8] + 0x1b0, and after main DT_INIT that pointer is the
       title's own TLS block, not the region this host installed. */
    if (mutex) {
        static int logs;
        if (logs < 24) {
            logs++;
            uint32_t word = 0;
            (void)safe_read(mutex, &word, sizeof word);
            const uint64_t probe_tlr =
                guest_tlr_for_tp(hook_guest_tp() ? hook_guest_tp() : this_guest_tls());
            const uint64_t probe_thread =
                probe_tlr ? *(const uint64_t *)(uintptr_t)(probe_tlr + 0x1f8) : 0;
            info("SdkMutexType::Unlock mutex=%p word=%#x tp=%#" PRIx64 " tlr=%#" PRIx64
                 " thread=%#" PRIx64 " id=%#x",
                 (void *)(uintptr_t)mutex, word, g_hook_tls.guest_tp, probe_tlr, probe_thread,
                 probe_thread ? *(const uint32_t *)(uintptr_t)(probe_thread + 0x1b0) : 0u);
        }
        /* Do the release here instead of running the SDK's Leave: Leave reads the
           thread object out of tpidrro_el0 and aborts ("this == NULL") whenever the
           title has re-pointed its thread pointer, which is always the case once
           the engine is running.  The word itself is all the kernel keeps. */
        const uint32_t owner = guest_thread_id(hook_guest_tp());
        const uint32_t result = d3_sync_unlock((uint32_t *)(uintptr_t)mutex, owner);
        if (result != 0)
            info("SdkMutexType::Unlock word=%#x owner=%#x -> %#x", *(const uint32_t *)(uintptr_t)mutex,
                 owner, result);
    }
    return 0;
}

static void restore_hook(uint64_t vaddr);

typedef struct {
    char name[0x301];
    uint8_t padding[3];
    uint8_t type;
    uint8_t reserved[3];
    int64_t size;
} GuestDirectoryEntry;

_Static_assert(sizeof(GuestDirectoryEntry) == 0x310, "Horizon directory entry ABI");

typedef struct {
    DIR *directory;
    uint32_t mode;
} GuestDirectory;

static GuestDirectory g_directories[32];
static pthread_mutex_t g_directory_mutex = PTHREAD_MUTEX_INITIALIZER;

static uint64_t hook_fs_open_directory(uint64_t out, uint64_t path, uint64_t mode) {
    if (!out || !path || !(mode & 3u) || (mode & ~UINT64_C(0x80000003)))
        return D3_FS_NOT_FOUND;
    char host[512];
    if (guest_data_host((const char *)(uintptr_t)path, host, sizeof host, 0) != 0)
        return D3_FS_NOT_FOUND;
    DIR *directory = opendir(host);
    if (!directory)
        return D3_FS_NOT_FOUND;
    pthread_mutex_lock(&g_directory_mutex);
    for (uint32_t index = 0; index < 32; index++) {
        if (g_directories[index].directory)
            continue;
        g_directories[index] = (GuestDirectory){directory, (uint32_t)mode};
        *(uint64_t *)(uintptr_t)out = index + 1;
        pthread_mutex_unlock(&g_directory_mutex);
        info("fs: OpenDirectory %s mode=%#" PRIx64 " -> %u", host, mode, index + 1);
        return 0;
    }
    pthread_mutex_unlock(&g_directory_mutex);
    closedir(directory);
    return D3_FS_NOT_FOUND;
}

static int fs_next_directory(GuestDirectory *directory, GuestDirectoryEntry *output) {
    struct dirent *entry;
    while ((entry = readdir(directory->directory)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        struct stat metadata;
        if (fstatat(dirfd(directory->directory), entry->d_name, &metadata, AT_SYMLINK_NOFOLLOW) != 0)
            continue;
        const int is_directory = S_ISDIR(metadata.st_mode);
        if ((!is_directory && !S_ISREG(metadata.st_mode)) ||
            !(directory->mode & (is_directory ? 1u : 2u)))
            continue;
        if (output) {
            memset(output, 0, sizeof *output);
            snprintf(output->name, sizeof output->name, "%s", entry->d_name);
            output->type = is_directory ? 0 : 1;
            output->size = is_directory || (directory->mode & 0x80000000u) ? 0 : metadata.st_size;
        }
        return 1;
    }
    return 0;
}

static uint64_t hook_fs_read_directory(uint64_t out, uint64_t buffer, uint64_t handle,
                                       uint64_t count) {
    if (!out || !handle || handle > 32 || (int64_t)count < 0 || (count && !buffer))
        return D3_FS_NOT_FOUND;
    pthread_mutex_lock(&g_directory_mutex);
    GuestDirectory *directory = &g_directories[handle - 1];
    if (!directory->directory) {
        pthread_mutex_unlock(&g_directory_mutex);
        return D3_FS_NOT_FOUND;
    }
    uint64_t filled = 0;
    while (filled < count && fs_next_directory(directory,
            &((GuestDirectoryEntry *)(uintptr_t)buffer)[filled]))
        filled++;
    *(int64_t *)(uintptr_t)out = (int64_t)filled;
    pthread_mutex_unlock(&g_directory_mutex);
    info("fs: ReadDirectory h=%" PRIu64 " -> %" PRIu64 " entries", handle, filled);
    return 0;
}

static uint64_t hook_fs_directory_count(uint64_t out, uint64_t handle) {
    if (!out || !handle || handle > 32)
        return D3_FS_NOT_FOUND;
    pthread_mutex_lock(&g_directory_mutex);
    GuestDirectory *directory = &g_directories[handle - 1];
    if (!directory->directory) {
        pthread_mutex_unlock(&g_directory_mutex);
        return D3_FS_NOT_FOUND;
    }
    const long position = telldir(directory->directory);
    rewinddir(directory->directory);
    int64_t count = 0;
    while (fs_next_directory(directory, NULL))
        count++;
    seekdir(directory->directory, position);
    *(int64_t *)(uintptr_t)out = count;
    pthread_mutex_unlock(&g_directory_mutex);
    return 0;
}

static uint64_t hook_fs_close_directory(uint64_t handle) {
    if (!handle || handle > 32)
        return D3_FS_NOT_FOUND;
    pthread_mutex_lock(&g_directory_mutex);
    GuestDirectory *directory = &g_directories[handle - 1];
    if (!directory->directory) {
        pthread_mutex_unlock(&g_directory_mutex);
        return D3_FS_NOT_FOUND;
    }
    closedir(directory->directory);
    memset(directory, 0, sizeof *directory);
    pthread_mutex_unlock(&g_directory_mutex);
    return 0;
}

/* nn::sf::hipc::GetPortProcessor(name) hands back a MITM resolver entry; for "hid"
   the SDK's entry fails its virtual connect, and because an entry exists the direct
   sm::GetServiceHandle path is never taken.  Reporting "no entry" forces the
   direct path, which goes through this host's sm service. */
static uint64_t hook_get_port_processor(uint64_t name) {
    static int logs;
    if (logs < 8) {
        logs++;
        info("sf: GetPortProcessor(%s) -> none",
             name ? (const char *)(uintptr_t)name : "(null)");
    }
    return 0;
}

/* ------------------------------------------------------------ hid probes -- */
/* Two probes on nn::hid's applet-resource path.  The SDK builds an
   IAppletResource proxy right after each CreateAppletResource reply and then
   sends GetSharedMemoryHandle on it, so the question is what the SDK used as
   that proxy's session.  Both probes log, then put the real function back and
   call it, which keeps the guest behaviour unchanged. */

static void probe_dump(const char *tag, uint64_t address, int words) {
    uint64_t values[16] = {0};
    if (!address || words < 1 || words > 16 || !safe_read(address, values, (uint64_t)words * 8)) {
        info("probe %s %#" PRIx64 " unreadable", tag, address);
        return;
    }
    for (int index = 0; index < words; index += 4)
        info("probe %s %#" PRIx64 " +%#x: %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64, tag,
             address, index * 8, values[index], values[index + 1], values[index + 2],
             values[index + 3]);
}

static uint64_t probe_call_site(uint64_t vaddr, const char *what, uint64_t a0, uint64_t a1,
                                uint64_t a2, uint64_t a3, uint64_t a4, uint64_t a5) {
    restore_hook(g_bias + vaddr);
    typedef uint64_t (*body_t)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
    body_t body = (body_t)(uintptr_t)(g_bias + vaddr);
    (void)what;
    return body(a0, a1, a2, a3, a4, a5);
}

/* nn::hid::detail::SharedMemoryAccessor::Activate: x0 is the hid facade the SDK
   asks for the applet resource, so its vtable names the owner of the path. */
static uint64_t hook_activate_probe(uint64_t self, uint64_t arg1, uint64_t arg2, uint64_t arg3,
                                    uint64_t arg4, uint64_t arg5) {
    static int logs;
    if (logs < 8) {
        logs++;
        const uint64_t site = g_hook_tls.guest_lr;
        info("probe Activate self=%#" PRIx64 " args=%#" PRIx64 " %#" PRIx64 " %#" PRIx64
             " %#" PRIx64 " %#" PRIx64 " lr=%#" PRIx64 " (%s+%#" PRIx64 ")",
             self, arg1, arg2, arg3, arg4, arg5, site, module_of(site),
             site >= g_bias ? site - g_bias : 0);
        probe_dump("Activate self", self, 8);
        uint64_t vtbl = 0;
        if (self && safe_read(self, &vtbl, sizeof vtbl))
            probe_dump("Activate vtbl", vtbl, 8);
        /* x1 points at the caller's own variable holding the object Activate
           sends the applet resource request through: name it and its method. */
        uint64_t object = 0;
        if (arg1 && safe_read(arg1, &object, sizeof object) && object) {
            probe_dump("Activate arg1 object", object, 8);
            uint64_t object_vtbl = 0;
            if (safe_read(object, &object_vtbl, sizeof object_vtbl))
                probe_dump("Activate arg1 vtbl", object_vtbl, 8);
        }
        probe_dump("hid statics", g_bias + 0xc9bb70u, 16);
        probe_dump("ipc buffer", d3_service_current_buffer(), 16);
        d3_dump_sdk_global(0xc9bb98u);
        d3_dump_sdk_global(0xc9bba8u);
    }
    return probe_call_site(0x2501e0u, "Activate", self, arg1, arg2, arg3, arg4, arg5);
}

/* The applet resource proxy's first method.  x0 is the object's CmifProxy
   subobject, whose +4 is the session handle the request goes out on. */
static uint64_t hook_gshm_probe(uint64_t self, uint64_t out, uint64_t arg2, uint64_t arg3,
                                uint64_t arg4, uint64_t arg5) {
    static int logs;
    if (logs < 8) {
        logs++;
        const uint64_t site = g_hook_tls.guest_lr;
        info("probe GetSharedMemoryHandle self=%#" PRIx64 " out=%#" PRIx64 " lr=%#" PRIx64
             " (%s+%#" PRIx64 ")",
             self, out, site, module_of(site), site >= g_bias ? site - g_bias : 0);
        if (self)
            probe_dump("proxy", self - 8, 8);
        probe_dump("ipc buffer", d3_service_current_buffer(), 16);
        d3_dump_sdk_global(0xc9bb98u);
    }
    return probe_call_site(0x26ce10u, "GetSharedMemoryHandle", self, out, arg2, arg3, arg4, arg5);
}

/* nn::hid::IHidServer::CreateAppletResource: x0 is the IHidServer proxy, x1
   holds the out-raw slot the aruid lands in, x2 addresses the out object the
   SDK builds from the reply and x4 is the holder the reply processing fills.
   The proxy the SDK then sends GetSharedMemoryHandle on comes out of here, so
   dump both the holder and whatever object it holds, before and after. */
static uint64_t hook_create_applet_resource(uint64_t self, uint64_t out, uint64_t object_arg,
                                            uint64_t command, uint64_t holder, uint64_t arg5) {
    static int logs;
    if (logs < 4) {
        logs++;
        const uint64_t site = g_hook_tls.guest_lr;
        info("probe CreateAppletResource self=%#" PRIx64 " out=%#" PRIx64 " object=%#" PRIx64
             " command=%#" PRIx64 " holder=%#" PRIx64 " arg5=%#" PRIx64 " lr=%#" PRIx64
             " (%s+%#" PRIx64 ")",
             self, out, object_arg, command, holder, arg5, site, module_of(site),
             site >= g_bias ? site - g_bias : 0);
        probe_dump("create before out", out, 4);
        probe_dump("create before object", object_arg, 4);
        probe_dump("create before holder", holder, 4);
        uint64_t before[4] = {0};
        if (holder && safe_read(holder, before, sizeof before))
            info("probe create holder value %#" PRIx64, before[0]);
        probe_dump("create ipc buffer", d3_service_current_buffer(), 16);
        d3_dump_sdk_global(0xc9bba8u);
    }
    restore_hook(g_bias + 0x26b690u);
    typedef uint64_t (*body_t)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
    uint64_t result = ((body_t)(uintptr_t)(g_bias + 0x26b690u))(self, out, object_arg, command,
                                                              holder, arg5);
    if (logs <= 4) {
        info("probe CreateAppletResource -> %#" PRIx64 " (%u)", result, (uint32_t)result);
        probe_dump("create after out", out, 4);
        probe_dump("create after object", object_arg, 4);
        probe_dump("create after holder", holder, 4);
        uint64_t object = 0;
        if (holder && safe_read(holder, &object, sizeof object) && object) {
            probe_dump("create result object", object, 8);
            uint64_t vtbl = 0;
            if (safe_read(object, &vtbl, sizeof vtbl))
                probe_dump("create result vtbl", vtbl, 4);
        }
        probe_dump("create ipc buffer after", d3_service_current_buffer(), 16);
    }
    return result;
}

static const GuestHook g_hooks[] = {
    /* Probes stay in the first 64 entries: restore_hook only keeps the
       original bytes of those. */
    {0x2501e0, (void *)hook_activate_probe, "probe: hid SharedMemoryAccessor::Activate"},
    {0x26ce10, (void *)hook_gshm_probe,
     "probe: hid IAppletResource::GetSharedMemoryHandle"},
    {0x26b690, (void *)hook_create_applet_resource, "probe: hid CreateAppletResource"},
    {0x205660, (void *)hook_fs_directory_count, "nn::fs::GetDirectoryEntryCount"},
    {0x2071c0, (void *)hook_fs_open_directory, "nn::fs::OpenDirectory"},
    {0x205550, (void *)hook_fs_read_directory, "nn::fs::ReadDirectory"},
    {0x2054c0, (void *)hook_fs_close_directory, "nn::fs::CloseDirectory"},
    /* NOT hooked any more.  Activate returns a Result and, on success, makes the
       SDK map hid's 256 KiB block; with the whole function replaced by "return
       success" the address it hands out stayed null, so the engine never saw a
       pad and relaunched the Controller applet in a loop (logcat: the applet=0xc
       sequence repeating, hid::GetSupportedNpadStyleSet polled ~170 times).
       Everything it needs is implemented now - hid cmd 0 hands out the block and
       svcMapSharedMemory seeds it (d3_hid_seed) - so let the real code run:
       expect "MapSharedMemory ... size=0x40000" and "hid: seeded npad 0" in the
       probe log.
    {0x2501e0, (void *)hook_success, "nn::hid::detail::SharedMemoryAccessor::Activate"}, */
    {0x349f30, (void *)hook_critical_enter,
     "nn::os::detail::InternalCriticalSectionImplByHorizon::Enter"},
    {0x3413f0, (void *)hook_mutex_unlock, "nn::os::SdkMutexType::Unlock"},
    /* GPU error reporting registers a system worker whose critical section this
       host never initializes (the SDK aborts on the NULL before the title runs).
       The GPU error event is not signalled here anyway, so the bring-up build
       skips the registration. */
    {0x33dfd0, (void *)hook_success, "nn::oe::SetupGpuErrorHandler"},
    {0x192600, (void *)hook_assert_failure, "nn::diag::detail::OnAssertionFailure(5 args)"},
    {0x192750, (void *)hook_assert_failure, "nn::diag::detail::OnAssertionFailure(4 args)"},
    {0x343100, (void *)hook_exit_process, "nn::os::ExitProcess"},
    /* HID getters whose detail call fails while the shared-memory accessor is a
       stub: the SDK wrapper turns that failure into AbortImpl("this == NULL"), and
       the engine aborts a whole thread.  Report the neutral value instead
       (Vertical hold, Handheld enabled, CommunicationMode 0). */
    {0x25ecd0, (void *)hook_success, "nn::hid::GetNpadJoyHoldType"},
    {0x25ee10, (void *)hook_success, "nn::hid::GetNpadHandheldActivationMode"},
    {0x25eeb0, (void *)hook_success, "nn::hid::GetNpadCommunicationMode"},
    {0x377c60, (void *)hook_get_port_processor, "nn::sf::hipc::GetPortProcessor"},
    {0x341f40, (void *)hook_tls_get, "nn::os::GetTlsValue"},
    {0x341f60, (void *)hook_tls_set, "nn::os::SetTlsValue"},
    {0x341540, (void *)hook_recursive_mutex_unlock, "nn::os::SdkRecursiveMutexType::Unlock"},
    {0x1925e0, (void *)hook_abort_impl, "nn::diag::detail::AbortImpl(f,f,f,i)"},
    {0x192500, (void *)hook_abort_impl, "nn::diag::detail::AbortImpl(f,f,f,r,f)"},
    {0x1924a0, (void *)hook_abort_impl, "nn::diag::detail::AbortImpl(f,f,f,i,r,exc,v)"},
    {0x4d9ea0, (void *)hook_cxa_throw, "__cxa_throw"},
    {0x4d72d8, (void *)hook_terminate, "std::terminate"},
    {0x531730, (void *)hook_raise_exception, "_Unwind_RaiseException"},
    {0x39e2d0, (void *)hook_time_initialize, "_ZN2nn4time10InitializeEv"},
    {0x39e5e0, (void *)hook_time_is_initialized, "_ZN2nn4time13IsInitializedEv"},
    {0x3a14a0, (void *)hook_time_get_current_time, "StandardUserSystemClock::GetCurrentTime"},
    {0x3a1520, (void *)hook_time_now, "StandardUserSystemClock::now"},
    {0x3a1820, (void *)hook_time_to_calendar, "ToCalendarTime"},
    {0x37b2e0, (void *)hook_success, "nn::socket::Initialize"},
    {0x37b300, (void *)hook_success, "nn::socket::Finalize"},
    {0x90650, (void *)hook_success, "nn::applet::SetCpuBoostMode"},
    {0x2275f0, (void *)hook_fs_rom_cache_size, "nn::fs::QueryMountRomCacheSize(Pm)"},
    {0x227710, (void *)hook_fs_rom_cache_size, "nn::fs::QueryMountRomCacheSize(Pm,AppId)"},
    {0x227830, (void *)hook_fs_rom_cache_size, "nn::fs::QueryMountRomCacheSize(Pm,i)"},
    {0x227960, (void *)hook_success, "nn::fs::MountRom(Pc,void*,u64)"},
    {0x227af0, (void *)hook_success, "nn::fs::MountRom(Pc,AppId,void*,u64)"},
    {0x227c80, (void *)hook_success, "nn::fs::MountRom(Pc,i,void*,u64)"},
    {0x23be20, (void *)hook_fs_addon_cache_size, "nn::fs::QueryMountAddOnContentCacheSize"},
    {0x23c050, (void *)hook_fs_mount_addon, "nn::fs::MountAddOnContent"},
    {0x204f80, (void *)hook_fs_unmount, "nn::fs::Unmount"},
    {0x206eb0, (void *)hook_fs_open_file, "nn::fs::OpenFile(FileHandle*,Pc,int)"},
    {0x205700, (void *)hook_fs_close_file, "nn::fs::CloseFile"},
    {0x205950, (void *)hook_fs_read_file, "nn::fs::ReadFile(h,off,buf,size)"},
    {0x205980, (void *)hook_fs_read_file_count, "nn::fs::ReadFile(out,h,off,buf,size)"},
    {0x205d50, (void *)hook_fs_get_file_size, "nn::fs::GetFileSize(s64*,h)"},
    {0x205f60, (void *)hook_fs_create_file, "nn::fs::CreateFile(Pc,s64)"},
    {0x208bb0, (void *)hook_fs_create_file, "nn::fs::CreateFile(Pc,s64,int)"},
    {0x205a20, (void *)hook_fs_write_file, "nn::fs::WriteFile(h,off,buf,size,opt)"},
    {0x205b60, (void *)hook_fs_flush_file, "nn::fs::FlushFile(h)"},
    {0x205c50, (void *)hook_fs_set_file_size, "nn::fs::SetFileSize(h,s64)"},
    {0x3c9c60, (void *)hook_success, "nn::vi::SetLayerScalingMode"},
    {0x3c9c70, (void *)hook_success, "nn::vi::SetLayerCrop"},
    {0x3c9da0, (void *)hook_success, "nn::vi::SetLayerPosition"},
    {0x3c9e20, (void *)hook_success, "nn::vi::SetLayerSize"},
    {0x3c9ea0, (void *)hook_success, "nn::vi::SetLayerZ"},
    {0x3c9f10, (void *)hook_success, "nn::vi::GetLayerZ"},
    {0x3c9fa0, (void *)hook_success, "nn::vi::SetLayerVisibility"},
    {0x3ca010, (void *)hook_success, "nn::vi::SetLayerAlpha"},
    {0x3ca0e0, (void *)hook_success, "nn::vi::AddToLayerStack"},
    {0x3ca150, (void *)hook_success, "nn::vi::RemoveFromLayerStack"},
    {0x3c6bf0, (void *)hook_success, "nn::vi::SetDisplayLayerStack"},
};

/* A hook site is entered by a direct branch from guest code, so tpidr_el0 is
   still the guest thread pointer when the hook body starts.  bionic resolves
   errno through the TCB ([tp + 8] + 0x300) and the guest TLS block holds zero
   there, so the first snprintf inside a hook faults at address 0x300 and hides
   whatever the guest was trying to report (every nn::diag::AbortImpl so far
   died in the abort hook instead of logging its message).  hook_stub.S therefore
   swaps in the *calling thread's* host TLS before the body runs.  The site stub
   stays 16 bytes because some hooked entry points are only 16 bytes apart. */

static uint64_t hook_guest_tp(void) {
    /* The thread's own region, never a pointer taken from shared state: both
       g_hook_tls.guest_tp and the veneer table slot are single words that two
       guest threads overwrite under each other, and resolving through the wrong
       one lands on another thread's thread object (nn::os TLS slots then read
       back as 0).  guest_tlr_for_tp maps a region to itself. */
    return this_guest_tls();
}

/* One body pointer per d3_hook_page entry (hook_stub.S indexes this table with
   the index it recovers from the entry that was called).  Filled in
   install_guest_hooks(); the assembler needs the symbol, so it is not static. */
#define HOOK_MAX 256
uint64_t g_hook_bodies[HOOK_MAX];
uint64_t g_veneer_resume;
extern void d3_veneer_bridge(void);

/* d3_hook_page lives in hook_stub.S: HOOK_MAX entries of "b d3_hook_stub".  A
   site stub branches to &d3_hook_page[index], which is what tells the stub which
   hook body to run. */
extern const uint32_t d3_hook_page[];

/* Original bytes of every hooked site, so a hook can put the real function back
   once it has prepared the state that function needs. */
static uint8_t g_hook_original[64][16];
static uint64_t g_hook_site[64];
static size_t g_hook_count;

static void restore_hook(uint64_t vaddr) {
    for (size_t index = 0; index < g_hook_count; index++) {
        if (g_hook_site[index] != vaddr)
            continue;
        /* The image's code pages are read-only by now (the segments got their
           final protections after the hooks were installed), so the page has to be
           opened for this write first. */
        const uint64_t page = vaddr & ~(uint64_t)(g_os_page - 1);
        if (mprotect((void *)(uintptr_t)page, g_os_page, PROT_READ | PROT_WRITE) != 0) {
            info("hook restore mprotect(%#" PRIx64 ") errno %d", page, errno);
            return;
        }
        memcpy((void *)(uintptr_t)vaddr, g_hook_original[index], 16);
        __builtin___clear_cache((char *)(uintptr_t)vaddr, (char *)(uintptr_t)vaddr + 16);
        if (mprotect((void *)(uintptr_t)page, g_os_page, PROT_READ | PROT_EXEC) != 0)
            info("hook restore mprotect(RX) errno %d", errno);
        info("hook %#" PRIx64 " restored to the real function", vaddr);
        return;
    }
}

static void install_guest_hooks(uint64_t base, uint64_t image_size) {
    if (g_display_width != 1600) {
        const uint64_t offset = 0x10e7858;
        const uint64_t letterbox_offset = 0x1eb0b10;
        if (offset + 24 > image_size || letterbox_offset + 4 > image_size ||
            d3_display_patch((uint32_t*)(uintptr_t)(base + offset),
                             (uint32_t*)(uintptr_t)(base + letterbox_offset), g_display_width, g_display_height))
            fail("native widescreen: guest resolution initializer differs from the verified update image");
        __builtin___clear_cache((char*)(uintptr_t)(base + offset), (char*)(uintptr_t)(base + offset + 24));
        info("native widescreen: docked=%ux%u aspect=%.6f (verified guest initializer)",
             g_display_width, g_display_height, (double)g_display_width / g_display_height);
        info("native widescreen: scene/UI letterbox aspect synchronized at guest vaddr=%#llx",
             (unsigned long long)letterbox_offset);
        const uint64_t menu_call = 0x11ad888, menu_trampoline = 0x129b4c4;
        const uint32_t menu_arguments[4] = {0x4eaa1d40, 0x4eab1d61, 0x4ea81d02, 0x4ea91d23};
        float menu_scale;
        if (menu_call + 4 > image_size || menu_trampoline + 12 > image_size ||
            memcmp((void*)(uintptr_t)(base + 0x11ad850), menu_arguments, sizeof menu_arguments) ||
            d3_display_menu_patch((uint32_t*)(uintptr_t)(base + menu_call),
                                  (uint32_t*)(uintptr_t)(base + menu_trampoline), g_display_width, &menu_scale))
            fail("native widescreen: menu camera call/padding differs from the verified update image");
        __builtin___clear_cache((char*)(uintptr_t)(base + menu_call), (char*)(uintptr_t)(base + menu_call + 4));
        __builtin___clear_cache((char*)(uintptr_t)(base + menu_trampoline), (char*)(uintptr_t)(base + menu_trampoline + 12));
        info("native widescreen: menu-only camera FOV scale=%.6f; gameplay projection unchanged", (double)menu_scale);
    }
    log_exec_maps();
    const size_t count = sizeof g_hooks / sizeof g_hooks[0];
    if (count > HOOK_MAX)
        fail("hook table has %zu entries, hook_stub.S only has %d", count, (int)HOOK_MAX);
    for (size_t index = 0; index < count; index++) {
        const GuestHook *hook = &g_hooks[index];
        if (hook->vaddr + 16 > image_size)
            fail("hook %s outside image", hook->name);
        /* The stub reads the body from this table; the site stub only carries the
           address of its own d3_hook_page entry. */
        g_hook_bodies[index] = (uint64_t)(uintptr_t)hook->target;
        const uint64_t entry = (uint64_t)(uintptr_t)&d3_hook_page[index];
        uint32_t *stub = (uint32_t *)(uintptr_t)(base + hook->vaddr);
        if (hook->vaddr == 0x204f80) {
            /* Unmount's first four instructions only save its frame. Preserve
               the SDK path for non-addon mounts; host addon mounts use our table. */
            const uint32_t expected[4] = {0xd10103ffu, 0xf9000bf5u, 0xa9024ff4u, 0xa9037bfdu};
            if (memcmp(stub, expected, sizeof expected)) fail("Unmount prologue changed");
            uint32_t *trampoline = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            if (trampoline == MAP_FAILED) fail("Unmount trampoline allocation failed");
            memcpy(trampoline, stub, 16);
            trampoline[4] = 0x58000050u; trampoline[5] = 0xd61f0200u;
            const uint64_t resume = base + hook->vaddr + 16;
            memcpy(trampoline + 6, &resume, 8);
            __builtin___clear_cache((char*)trampoline, (char*)trampoline + 32);
            if (mprotect(trampoline, 4096, PROT_READ | PROT_EXEC)) fail("Unmount trampoline protect failed");
            g_unmount_trampoline = (uint64_t)(uintptr_t)trampoline;
        }
        if (index < 64) {
            memcpy(g_hook_original[index], stub, 16);
            g_hook_site[index] = base + hook->vaddr;
            if (index + 1 > g_hook_count)
                g_hook_count = index + 1;
        }
        stub[0] = 0x58000050u; /* ldr x16, [pc, #8] */
        stub[1] = 0xd61f0200u; /* br x16 */
        memcpy(&stub[2], &entry, sizeof entry);
        __builtin___clear_cache((char *)stub, (char *)stub + 16);
        info("hook %s at %#" PRIx64 " -> %p", hook->name, base + hook->vaddr, hook->target);
    }
}

static void load_guest(const char *path) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    struct stat file_stat;
    Elf64_Ehdr header;
    uint64_t max_vaddr = 0;
    uint64_t raw_address;
    uint64_t base;
    uint64_t reserve_size;
    void *raw;
    Elf64_Dyn *dynamic = NULL;
    uint64_t rela_address = 0;
    uint64_t rela_size = 0;
    uint64_t rela_entry = 0;
    if (fd < 0)
        fail("open guest %s errno %d", path, errno);
    g_os_page = (size_t)sysconf(_SC_PAGESIZE);
    if (!g_os_page || (g_os_page & (g_os_page - 1)))
        fail("invalid host page size");
    if (fstat(fd, &file_stat) != 0)
        fail("stat guest %s errno %d", path, errno);
    read_guest(fd, &header, sizeof header, 0);
    if (memcmp(header.e_ident, ELFMAG, SELFMAG) != 0 || header.e_ident[EI_CLASS] != ELFCLASS64 ||
        header.e_ident[EI_DATA] != ELFDATA2LSB || header.e_type != ET_DYN || header.e_machine != EM_AARCH64)
        fail("guest is not ELF64 AArch64 PIE");
    if (header.e_phentsize != sizeof(Elf64_Phdr) || !header.e_phnum)
        fail("invalid guest program headers");
    g_guest_phnum = header.e_phnum;
    g_guest_phdr = calloc(g_guest_phnum, sizeof(*g_guest_phdr));
    if (!g_guest_phdr)
        fail("guest program headers allocation failed");
    read_guest(fd, g_guest_phdr, g_guest_phnum * sizeof(*g_guest_phdr), (off_t)header.e_phoff);
    for (size_t i = 0; i < g_guest_phnum; i++) {
        Elf64_Phdr *ph = &g_guest_phdr[i];
        if (ph->p_type == PT_LOAD) {
            if (!ph->p_memsz || ph->p_filesz > ph->p_memsz || ph->p_offset + ph->p_filesz > (uint64_t)file_stat.st_size)
                fail("invalid guest load segment");
            uint64_t segment_end = ph->p_vaddr + ph->p_memsz;
            if (segment_end > max_vaddr)
                max_vaddr = segment_end;
        } else if (ph->p_type == PT_DYNAMIC) {
            dynamic = (Elf64_Dyn *)(uintptr_t)ph->p_vaddr;
        }
    }
    if (!max_vaddr || !dynamic)
        fail("guest has no load or dynamic segments");
    reserve_size = align_up_guest(max_vaddr, 0x4000);
    raw = mmap(NULL, (size_t)(reserve_size + 0x4000), PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (raw == MAP_FAILED)
        fail("guest address reserve errno %d", errno);
    raw_address = (uint64_t)(uintptr_t)raw;
    base = align_up_guest(raw_address, 0x4000);
    if ((base != raw_address && munmap((void *)(uintptr_t)raw_address, (size_t)(base - raw_address)) != 0) ||
        munmap((void *)(uintptr_t)(base + reserve_size), (size_t)(raw_address + 0x4000 - base)) != 0)
        fail("guest address trim errno %d", errno);
    for (size_t i = 0; i < g_guest_phnum; i++) {
        Elf64_Phdr *ph = &g_guest_phdr[i];
        if (ph->p_type != PT_LOAD)
            continue;
        uint64_t map_size = align_up_guest(ph->p_memsz, g_os_page);
        void *mapped = mmap((void *)(uintptr_t)(base + ph->p_vaddr), (size_t)map_size,
                            PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0);
        if (mapped == MAP_FAILED)
            fail("guest segment map %#" PRIx64 " errno %d", (uint64_t)ph->p_vaddr, errno);
        read_guest(fd, (void *)(uintptr_t)(base + ph->p_vaddr), (size_t)ph->p_filesz, (off_t)ph->p_offset);
    }
    close(fd);
    dynamic = (Elf64_Dyn *)(uintptr_t)(base + (uint64_t)(uintptr_t)dynamic);
    for (Elf64_Dyn *entry = dynamic; entry->d_tag != DT_NULL; entry++) {
        if (entry->d_tag == DT_RELA)
            rela_address = entry->d_un.d_ptr;
        else if (entry->d_tag == DT_RELASZ)
            rela_size = entry->d_un.d_val;
        else if (entry->d_tag == DT_RELAENT)
            rela_entry = entry->d_un.d_val;
    }
    if (rela_entry != sizeof(Elf64_Rela) || rela_size % rela_entry)
        fail("invalid guest RELA table");
    Elf64_Rela *relocations = (Elf64_Rela *)(uintptr_t)(base + rela_address);
    for (uint64_t offset = 0; offset < rela_size; offset += rela_entry) {
        Elf64_Rela *relocation = (Elf64_Rela *)((unsigned char *)relocations + offset);
        if (ELF64_R_TYPE(relocation->r_info) != R_AARCH64_RELATIVE)
            fail("unsupported guest relocation type %u", (unsigned)ELF64_R_TYPE(relocation->r_info));
        if (relocation->r_offset + sizeof(uint64_t) > max_vaddr)
            fail("guest relocation outside image");
        *(uint64_t *)(uintptr_t)(base + relocation->r_offset) = base + (uint64_t)relocation->r_addend;
    }
    /* This image was repacked by a tool that applied only RELATIVE records, so the
       original module's other relocations (the 246 ABS64 slots for
       __cxa_pure_virtual, rtld's 9 __rel_* pointers and all 529 JUMP_SLOT imports)
       were never written and every call through those slots failed.  The table in
       guest_relocs.h restores them; both fields are image offsets. */
    {
        uint32_t done = 0;
        uint32_t skipped = 0;
        for (uint32_t index = 0; index < (uint32_t)D3_GUEST_RELOC_COUNT; index++) {
            const GuestReloc *reloc = &g_guest_relocs[index];
            if (reloc->slot + sizeof(uint64_t) > max_vaddr || reloc->target > max_vaddr) {
                skipped++;
                continue;
            }
            *(uint64_t *)(uintptr_t)(base + reloc->slot) = base + (uint64_t)reloc->target;
            done++;
        }
        info("guest: applied %u recovered relocations (%u out of range)", (unsigned)done,
             (unsigned)skipped);
    }
    /* The image is still writable here: patch the SDK entry points before the
       segment protections go on. */
    install_guest_hooks(base, reserve_size);
    {
        /* The veneer stores the caller's tpidr_el0 at table + 0x10 and calls the
           dispatcher with (kind, extra, saved).  Its null check on the dispatch
           pointer is redundant (the host always installs it), and the slot it
           frees passes that thread pointer in x3 instead: reading the table slot
           after the fact raced with the other guest thread's veneer, which made
           one thread resolve tpidrro_el0 -- and therefore its mutex owner id --
           to the other thread's region. */
        uint32_t *veneer = (uint32_t *)(uintptr_t)(base + D3_VENEER_BASE);
        if (veneer[0x7cu / 4] != 0xd53bd051u || veneer[0xa4u / 4] != 0xf9400a11u)
            fail("unexpected veneer TLS sequence at %#" PRIx64, base + D3_VENEER_BASE + 0x7c);
        const uint64_t bridge = (uint64_t)(uintptr_t)d3_veneer_bridge;
        veneer[0x7cu / 4] = 0x58000050u;
        veneer[0x80u / 4] = 0xd61f0200u;
        memcpy(&veneer[0x84u / 4], &bridge, sizeof bridge);
        g_veneer_resume = base + D3_VENEER_BASE + 0xacu;
        if (veneer[0x174u / 4] != 0xd61f0200u)
            fail("unexpected veneer return at %#" PRIx64, base + D3_VENEER_BASE + 0x174);
    }
    for (size_t i = 0; i < g_guest_phnum; i++) {
        if (g_guest_phdr[i].p_type == PT_LOAD)
            protect_guest_segment(base, &g_guest_phdr[i]);
    }
    g_guest = (void *)(uintptr_t)base;
    g_bias = base;
    g_image = reserve_size;
    g_table = (uint64_t *)(uintptr_t)(base + D3_HOST_TABLE);
    d3_sync_enable_address_cache(1);
    info("guest mapped base=%" PRIx64 " size=%" PRIx64 " rela=%" PRIu64, base, reserve_size, rela_size / rela_entry);
}

static void add_fixed(uint64_t base, uint64_t size, uint32_t state, uint32_t perm) {
    if (!size)
        return;
    if (g_nfixed >= MAX_FIXED)
        fail("too many fixed regions");
    g_fixed[g_nfixed].base = base;
    g_fixed[g_nfixed].size = size;
    g_fixed[g_nfixed].state = state;
    g_fixed[g_nfixed].perm = perm;
    g_nfixed++;
}

static int region_cmp(const void *left, const void *right) {
    const Region *a = left;
    const Region *b = right;
    if (a->base < b->base)
        return -1;
    if (a->base > b->base)
        return 1;
    return 0;
}

static void overlay_region(Region overlay) {
    Region regions[MAX_REG];
    int count = 0;
    uint64_t end = overlay.base + overlay.size;
    for (int i = 0; i < g_nreg; i++) {
        Region region = g_reg[i];
        uint64_t region_end = region.base + region.size;
        if (region_end <= overlay.base || region.base >= end) {
            if (count >= MAX_REG)
                fail("too many overlay regions");
            regions[count++] = region;
            continue;
        }
        if (region.base < overlay.base) {
            if (count >= MAX_REG)
                fail("too many overlay regions");
            regions[count++] = (Region){region.base, overlay.base - region.base, region.state, region.perm};
        }
        if (region_end > end) {
            if (count >= MAX_REG)
                fail("too many overlay regions");
            regions[count++] = (Region){end, region_end - end, region.state, region.perm};
        }
    }
    if (count >= MAX_REG)
        fail("too many overlay regions");
    regions[count++] = overlay;
    memcpy(g_reg, regions, (size_t)count * sizeof regions[0]);
    g_nreg = count;
}

static void compose_regions(void) {
    d3_sync_invalidate_address_cache();
    g_nreg = 0;
    for (int i = 0; i < g_nfixed; i++) {
        if (g_nreg >= MAX_REG)
            fail("too many regions");
        g_reg[g_nreg++] = g_fixed[i];
    }
    if (g_heap_cap) {
        if (g_heap_cur) {
            if (g_nreg >= MAX_REG)
                fail("too many regions");
            g_reg[g_nreg++] = (Region){g_heap, g_heap_cur, MEM_NORMAL, PERM_RW};
        }
        /* The cap is only a host-side reservation, not something the guest asked
           for, so the uncommitted tail is not a region at all: query_memory's
           gap path already reports address space outside every region as
           MEM_FREE, which is what Horizon says and what the SDK's
           virtual-address allocator needs (it rejects any candidate whose
           state is not MEM_FREE).  Listing the tail as a region also made every
           later MapSharedMemory into it look like an overlap to
           compose_regions. */
    }
    for (int i = 0; i < MAX_STACK_MAPS; i++) {
        const StackMap *mapping = &g_stack_maps[i];
        if (!mapping->size)
            continue;
        overlay_region((Region){mapping->source, mapping->size, mapping->source_state, 0});
        overlay_region((Region){mapping->destination, mapping->size, MEM_STACK, PERM_RW});
    }
    qsort(g_reg, (size_t)g_nreg, sizeof g_reg[0], region_cmp);
    for (int i = 1; i < g_nreg; i++) {
        uint64_t prev_end = g_reg[i - 1].base + g_reg[i - 1].size;
        if (prev_end > g_reg[i].base)
            fail("overlapping regions %#llx and %#llx",
                 (unsigned long long)g_reg[i - 1].base, (unsigned long long)g_reg[i].base);
    }
}

static void log_regions_once(void) {
    if (g_regions_logged)
        return;
    g_regions_logged = 1;
    for (int i = 0; i < g_nreg; i++)
        info("region %d base=%" PRIx64 " size=%" PRIx64 " state=%u perm=%u",
             i, g_reg[i].base, g_reg[i].size, g_reg[i].state, g_reg[i].perm);
}

static void register_guest_segment(const Elf64_Phdr *ph) {
    uint64_t start = g_bias + ph->p_vaddr;
    uint64_t end = align_up_guest(start + ph->p_memsz, g_os_page);
    uint32_t perm = 0;
    if (ph->p_flags & PF_R)
        perm |= PERM_R;
    if (ph->p_flags & PF_W)
        perm |= PERM_W;
    if (ph->p_flags & PF_X)
        perm |= PERM_X;
    if ((ph->p_flags & (PF_W | PF_X)) == (PF_W | PF_X)) {
        uint64_t text_end = ph->p_vaddr == D3_SDK_BASE ? g_bias + D3_SDK_TEXT_END : g_bias + D3_MAIN_TEXT_END;
        uint64_t rx_end = align_up_guest(text_end, g_os_page);
        add_fixed(start, rx_end - start, MEM_CODE, PERM_R | PERM_X);
        if (end > rx_end)
            add_fixed(rx_end, end - rx_end, MEM_CODE_DATA, PERM_RW);
        return;
    }
    add_fixed(start, end - start, (ph->p_flags & PF_X) ? MEM_CODE : MEM_CODE_DATA, perm);
}

static void reserve_heap(void) {
#ifdef D3_WITH_GPU
    extern void *d3_gpu_guest_heap(uint64_t *size);
    void *backing = d3_gpu_guest_heap(&g_heap_cap);
    if (!backing)
        fail("GPU-backed guest heap reserve failed");
    g_heap = (uint64_t)(uintptr_t)backing;
    g_heap_cur = 0;
    info("GPU-backed heap reserve %" PRIx64 " cap %" PRIx64, g_heap, g_heap_cap);
    return;
#endif
    static const uint64_t tries[] = {0xC0000000ull, 0x80000000ull, 0x40000000ull, 0x20000000ull};
    for (size_t i = 0; i < sizeof tries / sizeof tries[0]; i++) {
        void *ptr = mmap(0, (size_t)tries[i], PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (ptr == MAP_FAILED)
            continue;
        g_heap = (uint64_t)(uintptr_t)ptr;
        g_heap_cap = tries[i];
        g_heap_cur = 0;
            info("heap reserve %" PRIx64 " cap %" PRIx64, g_heap, g_heap_cap);
        return;
    }
    fail("heap reserve failed errno %d", errno);
}

/* One thread-local region per guest thread.  The SDK keeps the running thread's
   id in the thread object hanging off the region (mrs tpidrro_el0 ->
   region + 0x1000; [region + 0x1000 + 0x1f8] -> thread object; [thread + 0x1b0]
   -> id) and its critical sections compare that id with a lock word's owner.  A
   single shared region made the main thread inherit the worker's id, so
   unlocking a mutex it did own failed its own ownership check and the SDK
   aborted ("this == NULL").  The three pages are contiguous so the region can be
   derived from tpidr_el0 alone. */
#define MAX_GUEST_REGIONS 256
static uint64_t g_regions[MAX_GUEST_REGIONS];
static int g_region_count;

/* Only regions this host mapped may be used as a thread's guest TLS: the map is
   also fed with the title's own thread pointers, and resolving one of those back
   to itself fabricates a thread object out of the title's TLS block (which is
   what made nn::os read a NULL thread object and abort). */
static int is_guest_region(uint64_t tls) {
    const int count = __atomic_load_n(&g_region_count, __ATOMIC_ACQUIRE);
    for (int index = 0; index < count; index++) {
        if (g_regions[index] == tls)
            return 1;
    }
    return 0;
}

static uint64_t guest_region_alloc(void) {
    void *region = mmap(0, GUEST_TLS_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS,
                        -1, 0);
    if (region == MAP_FAILED)
        fail("guest tls allocation errno %d", errno);
    const uint64_t tls = (uint64_t)(uintptr_t)region;
    if (g_region_count < MAX_GUEST_REGIONS)
        g_regions[__atomic_fetch_add(&g_region_count, 1, __ATOMIC_ACQ_REL)] = tls;
    const uint64_t tlr = tls + GUEST_TLR_OFFSET;
    *(uint16_t *)(uintptr_t)(tlr + 0x100) = 0;
    *(uint16_t *)(uintptr_t)(tlr + 0x102) = 0;
    *(uint64_t *)(uintptr_t)(tlr + 0x1f0) = tls;
    *(uint64_t *)(uintptr_t)(tlr + 0x1f8) = tls + GUEST_THREAD_OFFSET;
    return tls;
}

/* Per-thread guest state, keyed by the kernel tid.  A __thread variable cannot be
   used: a hook runs with whatever host thread pointer the trampoline installed,
   and that pointer is one global word shared by every guest thread, so __thread
   reads resolved to another thread's block (the boot thread was seen resolving to
   three different worker regions, which made nn::os TLS slots read back as 0).
   Keying by tid avoids TLS completely. */
#define MAX_THREAD_REGIONS 128
static struct {
    pid_t tid;
    uint64_t tls;
    uint64_t host_tp;
    uint64_t host_x18;
    int used;
} g_thread_regions[MAX_THREAD_REGIONS];
static pthread_mutex_t g_thread_region_mutex = PTHREAD_MUTEX_INITIALIZER;

static int thread_region_slot(pid_t tid, int create) {
    int free_slot = -1;
    for (int index = 0; index < MAX_THREAD_REGIONS; index++) {
        if (g_thread_regions[index].used && g_thread_regions[index].tid == tid)
            return index;
        if (!g_thread_regions[index].used && free_slot < 0)
            free_slot = index;
    }
    if (!create || free_slot < 0)
        return -1;
    g_thread_regions[free_slot].used = 1;
    g_thread_regions[free_slot].tid = tid;
    return free_slot;
}

/* The thread's own host (bionic) thread pointer.  Guest code runs with
   TPIDR_EL0 pointing at *its* TLS, and the veneer dispatcher has to switch back to
   this value before touching host libc (mutexes, logging, errno) or the libc
   reads garbage; the trampoline cannot look it up, so it is cached here per tid. */
static void thread_region_set_host_tp(uint64_t host_tp) {
    uint64_t host_x18;
    __asm__ volatile("mov %0, x18" : "=r"(host_x18));
    const pid_t tid = (pid_t)syscall(SYS_gettid);
    pthread_mutex_lock(&g_thread_region_mutex);
    const int slot = thread_region_slot(tid, 1);
    if (slot >= 0 && host_tp) {
        g_thread_regions[slot].host_tp = host_tp;
        g_thread_regions[slot].host_x18 = host_x18;
    }
    pthread_mutex_unlock(&g_thread_region_mutex);
}

static uint64_t thread_region_host_tp(void) {
    const pid_t tid = (pid_t)syscall(SYS_gettid);
    pthread_mutex_lock(&g_thread_region_mutex);
    const int slot = thread_region_slot(tid, 0);
    const uint64_t host_tp = slot >= 0 ? g_thread_regions[slot].host_tp : 0;
    pthread_mutex_unlock(&g_thread_region_mutex);
    return host_tp;
}

/* Faults on threads that never ran guest code are the framework's business: ART
   uses SIGSEGV for implicit null checks and installs its own handler, and this
   process-wide handler used to swallow those faults (the "wild jump" logs were
   actually libart JIT code).  Read-only scan, no mutex: this runs in a signal
   handler and the worst case is a stale answer. */
static int thread_is_guest(pid_t tid) {
    for (int index = 0; index < MAX_THREAD_REGIONS; index++) {
        if (g_thread_regions[index].used && g_thread_regions[index].tid == tid)
            return 1;
    }
    return 0;
}

/* Lock-free host thread pointer lookup for the guest's current thread.  Leaf
   helper called from hook_stub.S while TPIDR_EL0 still holds the *guest's*
   thread pointer, so it must not touch TLS (bionic's errno, stack canary and
   pthread internals all resolve through tpidr_el0) and must not call libc:
   the tid comes from a raw syscall, the pointer from the tid-keyed table. */
typedef struct {
    uint64_t tp;
    uint64_t x18;
} HostThreadState;

HostThreadState d3_host_tp_current(void) {
    register uint64_t number __asm__("x8") = 178; /* SYS_gettid on arm64 */
    register uint64_t result __asm__("x0");
    __asm__ volatile("svc #0" : "=r"(result) : "r"(number) : "memory");
    const uint64_t tid = result;
    for (int index = 0; index < MAX_THREAD_REGIONS; index++) {
        if (g_thread_regions[index].used && (uint64_t)g_thread_regions[index].tid == tid)
            return (HostThreadState){g_thread_regions[index].host_tp,
                                      g_thread_regions[index].host_x18};
    }
    return (HostThreadState){0, 0};
}

static uint64_t this_guest_tls(void) {
    const pid_t tid = (pid_t)syscall(SYS_gettid);
    pthread_mutex_lock(&g_thread_region_mutex);
    int slot = thread_region_slot(tid, 1);
    if (slot >= 0 && g_thread_regions[slot].tls == 0)
        g_thread_regions[slot].tls = guest_region_alloc();
    const uint64_t tls = slot >= 0 ? g_thread_regions[slot].tls : 0;
    pthread_mutex_unlock(&g_thread_region_mutex);
    return tls;
}

/* A guest thread this host spawned already owns a region: record it instead of
   letting the first hook allocate a second one for the same thread. */
static void thread_region_assign(uint64_t tls) {
    const pid_t tid = (pid_t)syscall(SYS_gettid);
    pthread_mutex_lock(&g_thread_region_mutex);
    const int slot = thread_region_slot(tid, 1);
    if (slot >= 0 && tls)
        g_thread_regions[slot].tls = tls;
    pthread_mutex_unlock(&g_thread_region_mutex);
}


/* The thread-local region of the guest thread that is running right now.  It
   must come from host thread state, not from a table slot: both guest threads
   stored their tpidr_el0 into the same word before every dispatch, so one thread
   could read the other's thread object -- and with it the other's mutex owner id
   -- which made nn::os::SdkMutexType::Unlock abort on a mutex the thread did
   hold. */
static uint64_t current_guest_region(void) {
    /* The veneer stores the caller's tpidr_el0 into the table right before it
       dispatches, so this is the dispatching thread's own region.  guest_call's
       host TLS is not usable here: the veneer installs the host TLS recorded in
       the table, which is one thread's TCB for every guest thread. */
    return guest_tlr_for_tp(this_guest_tls());
}

static void prepare_memory(void) {
    void *stack_map = map_pages(STACK_REGION_SIZE, PROT_NONE);
    g_stack_region = (uint64_t)(uintptr_t)stack_map;
    g_stack = g_stack_region + STACK_REGION_SIZE - STACK_SIZE;
    g_guard = g_stack - GUARD_SIZE;
    if (mprotect((void *)(uintptr_t)g_stack, STACK_SIZE, PROT_READ | PROT_WRITE) != 0)
        fail("stack mprotect errno %d", errno);
    g_tls = guest_region_alloc();
    info("layout: alias=%#" PRIx64 " cap=%#" PRIx64 " stack=%#" PRIx64 " region=%#" PRIx64,
         g_alias, g_alias_cap, g_stack_region, g_tls);
    g_tlr = g_tls + GUEST_TLR_OFFSET;
    g_thread = g_tls + GUEST_THREAD_OFFSET;
    g_guest_tp = g_tls;
    struct timespec boot;
    /* nn::os::detail::AddressRegionManager (the VAMM the sdk builds from the
       GetInfo alias region) commits its bookkeeping page and every later
       allocation with MapPhysicalMemory, so the region itself is reserved
       PROT_NONE and gets read/write pages on demand (alias_commit). */
#ifdef D3_WITH_GPU
    extern void *d3_gpu_guest_alias(uint64_t *size);
    uint64_t alias_size = 0;
    void *alias = d3_gpu_guest_alias(&alias_size);
#else
    void *alias = mmap(0, (size_t)ALIAS_SIZE, PROT_NONE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
#endif
    void *exc = map_pages(EXC_SIZE, PROT_READ | PROT_WRITE);
    if (alias == MAP_FAILED)
        fail("alias reserve errno %d", errno);
    if (clock_gettime(CLOCK_MONOTONIC, &boot) != 0)
        fail("clock errno %d", errno);
    g_alias = (uint64_t)(uintptr_t)alias;
    g_alias_cap = ALIAS_SIZE;
    g_exc = (uint64_t)(uintptr_t)exc;
    g_tick_base = (uint64_t)boot.tv_sec * 1000000000ull + (uint64_t)boot.tv_nsec;
    info("alias %" PRIx64 " exc %" PRIx64, g_alias, g_exc);
    reserve_heap();
}

static void register_fixed(void) {
    for (size_t i = 0; i < g_guest_phnum; i++) {
        if (g_guest_phdr[i].p_type == PT_LOAD && g_guest_phdr[i].p_memsz)
            register_guest_segment(&g_guest_phdr[i]);
    }
    g_found_guest = 1;
    if (!g_found_guest)
        fail("libd3guest.so has no program headers");
    add_fixed(g_guard, GUARD_SIZE, MEM_INACCESSIBLE, 0);
    add_fixed(g_stack, STACK_SIZE, MEM_STACK, PERM_RW);
    add_fixed(g_tlr, PAGE_SIZE, MEM_THREAD_LOCAL, PERM_RW);
    add_fixed(g_tls, PAGE_SIZE, MEM_THREAD_LOCAL, PERM_RW);
    add_fixed(g_thread, PAGE_SIZE, MEM_NORMAL, PERM_RW);
    add_fixed(g_exc, EXC_SIZE, MEM_NORMAL, PERM_RW);
    add_fixed(g_alias, ALIAS_SIZE, MEM_NORMAL, PERM_RW);
    compose_regions();
    log_regions_once();
}

static void set_saved(d3_saved *saved, uint32_t reg, uint64_t value) {
    if (reg > 30)
        fail("bad register %u", reg);
    saved->x[reg] = value;
    if (reg == 16 || reg == 17) {
        uint64_t *slot = (uint64_t *)((unsigned char *)saved + sizeof(d3_saved));
        slot[reg - 16] = value;
    }
}

static void set_heap(d3_saved *saved) {
    d3_sync_invalidate_address_cache();
    uint64_t size = saved->x[1];
    uint64_t page = (size + (PAGE_SIZE - 1)) & ~(uint64_t)(PAGE_SIZE - 1);
    if (page > g_heap_cap) {
        info("SetHeapSize reject size=%" PRIx64 " cap=%" PRIx64, size, g_heap_cap);
        set_saved(saved, 0, 0xD401);
        set_saved(saved, 1, 0);
        return;
    }
    if (page > g_heap_cur) {
        if (mprotect((void *)(uintptr_t)(g_heap + g_heap_cur), (size_t)(page - g_heap_cur),
                     PROT_READ | PROT_WRITE) != 0) {
            info("SetHeapSize mprotect errno %d", errno);
            set_saved(saved, 0, 0xD401);
            set_saved(saved, 1, 0);
            return;
        }
#ifdef D3_WITH_GPU
        d3_gpu_cpu_memory_permission(g_heap + g_heap_cur, page - g_heap_cur, 1);
#endif
    } else if (page < g_heap_cur) {
#ifdef D3_WITH_GPU
        d3_gpu_cpu_memory_permission(g_heap + page, g_heap_cur - page, 0);
#endif
        if (mprotect((void *)(uintptr_t)(g_heap + page), (size_t)(g_heap_cur - page), PROT_NONE) != 0)
            fail("SetHeapSize shrink errno %d", errno);
    }
    g_heap_cur = page;
    compose_regions();
    set_saved(saved, 0, 0);
    set_saved(saved, 1, g_heap);
    info("SetHeapSize size=%" PRIx64 " base=%" PRIx64, size, g_heap);
}

static void fill_info(MemInfo *out, uint64_t addr, uint64_t size, uint32_t state, uint32_t perm) {
    out->addr = addr;
    out->size = size;
    out->state = state;
    out->attr = 0;
    out->perm = perm;
    out->ipc = 0;
    out->device = 0;
    out->pad = 0;
}

static void query_memory(d3_saved *saved) {
    uint64_t info_ptr = saved->x[0];
    uint64_t addr = saved->x[2];
    MemInfo out;
    uint64_t start = 0;
    uint64_t end = 1ull << 48;
    int inside = 0;
    if (!info_ptr)
        fail("QueryMemory null MemoryInfo");
    for (int i = 0; i < g_nreg; i++) {
        if (addr >= g_reg[i].base && addr < g_reg[i].base + g_reg[i].size) {
            fill_info(&out, g_reg[i].base, g_reg[i].size, g_reg[i].state, g_reg[i].perm);
            inside = 1;
            break;
        }
    }
    if (!inside) {
        for (int i = 0; i < g_nreg; i++) {
            if (g_reg[i].base > addr) {
                end = g_reg[i].base;
                break;
            }
            if (g_reg[i].base + g_reg[i].size > start)
                start = g_reg[i].base + g_reg[i].size;
        }
        if (!(start <= addr && addr < end))
            fail("QueryMemory gap addr=%" PRIx64, addr);
        fill_info(&out, start, end - start, MEM_FREE, 0);
    }
    for (int i = 0; i < MAX_STACK_MAPS; i++) {
        const StackMap *mapping = &g_stack_maps[i];
        if (mapping->size && addr >= mapping->source && addr - mapping->source < mapping->size) {
            out.attr |= 1u; /* MemoryAttribute::Locked while mapped as a stack. */
            break;
        }
    }
    memcpy((void *)(uintptr_t)info_ptr, &out, sizeof out);
    set_saved(saved, 0, 0);
    set_saved(saved, 1, 0);
    if (g_query_logs < 8) {
        g_query_logs++;
        info("QueryMemory addr=%" PRIx64 " base=%" PRIx64 " size=%" PRIx64 " state=%u perm=%u",
             addr, out.addr, out.size, out.state, out.perm);
    }
}

static uint64_t ticks(void) {
    struct timespec now;
    uint64_t ns;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0)
        fail("clock_gettime errno %d", errno);
    ns = (uint64_t)now.tv_sec * 1000000000ull + (uint64_t)now.tv_nsec - g_tick_base;
    return ns * 12 / 625;
}

/* The one unresolved import. nnsdk asks for the application's user exception
   stack, passing an out slot for its size and taking the base back in x0. */
static void default_user_exception_stack(d3_saved *saved) {
    uint64_t out = saved->x[0];
    uint64_t size = EXC_SIZE;
    if (!out)
        fail("nnosGetDefaultUserExceptionStackForApplication null out");
    memcpy((void *)(uintptr_t)out, &size, sizeof size);
    set_saved(saved, 0, g_exc);
    info("GetDefaultUserExceptionStack base=%" PRIx64 " size=%" PRIx64, g_exc, size);
}

/* One guest thread, so any stable non-zero id works. */
#define D3_THREAD_ID 1ull

/* The SDK keeps the running thread's id in the thread object hanging off the
   thread-local region (mrs tpidrro_el0 -> tlr; [tlr + 0x1f8] -> thread object;
   [thread + 0x1b0] -> thread id) and its critical sections compare that id with
   the lock word's owner.  Logging both sides makes an owner mismatch visible
   before it turns into an SDK abort. */
static void log_thread_id(const char *what, uint32_t *mutex, uint32_t tag) {
    const uint64_t tlr = current_guest_region();
    const uint64_t thread = *(const uint64_t *)(uintptr_t)(tlr + 0x1f8);
    const uint32_t id =
        thread ? *(const uint32_t *)(uintptr_t)(thread + 0x1b0) : 0xFFFFFFFFu;
    uint32_t word = 0;
    if (mutex)
        (void)safe_read((uint64_t)(uintptr_t)mutex, &word, sizeof word);
    const uint64_t tp = current_guest_region() - GUEST_TLR_OFFSET;
    info("%s mutex=%p word=%#x tag=%#x tls=%#" PRIx64 " thread=%#" PRIx64 " id=%#x",
         what, (void *)mutex, word, tag, tp, thread, (unsigned)id);
}

static void get_thread_id(d3_saved *saved) {
    /* Horizon returns a unique id per thread and the SDK stores it as the owner
       of every mutex the thread takes; a constant id made the boot thread and
       the first guest worker look like the same lock owner. */
    const uint64_t id = (uint64_t)gettid();
    set_saved(saved, 0, 0);
    set_saved(saved, 1, id);
    info("GetThreadId handle=%" PRIx64 " = %" PRIx64, saved->x[2], id);
}

/* Horizon reports the main thread at priority 0x20; the game maps it with
   `priority - 0x1c` when it builds its own scheduler threads. */
#define D3_THREAD_PRIORITY 0x20u

/* The sdk trampoline stores the value the kernel returns in x1 into the out
   pointer, so every scalar out parameter has to come back in x1. */
static void get_thread_priority(d3_saved *saved) {
    static uint32_t logs;
    uint32_t priority = D3_THREAD_PRIORITY;
    set_saved(saved, 0, 0);
    set_saved(saved, 1, priority);
    if (logs < 8) {
        logs++;
        info("GetThreadPriority handle=%" PRIx64 " = %u", saved->x[2], priority);
    }
}

static void probe_sysinfo(uint64_t id, uint64_t sub, uint32_t address) {
    static uint8_t seen[256];
    static int fd = -1;
    char line[200];
    int len;

    if (id >= sizeof seen)
        return;
    if (seen[id] >= 6)
        return;
    seen[id]++;
    if (fd < 0) {
        fd = open(PROBE_INFO_PATH, O_WRONLY | O_CREAT | O_APPEND, 0666);
        if (fd >= 0)
            (void)ftruncate(fd, 0);
    }
    if (fd < 0)
        return;
    len = snprintf(line, sizeof line, "id=%" PRIu64 " x3=%#" PRIx64 " lr=%#" PRIx64 "\n",
                   id, sub, (uint64_t)address);
    if (len > 0)
        (void)write(fd, line, (size_t)len < sizeof line ? (size_t)len : sizeof line - 1);
}

static void get_info(d3_saved *saved) {
    uint64_t id = saved->x[1];
    uint64_t value = 0;
    switch (id) {
    case I_CORE_MASK: value = 7; break;
    case I_PRIORITY_MASK: value = 0; break;
    case I_ALIAS_ADDR: value = g_alias; break;
    case I_ALIAS_SIZE: value = g_alias_cap; break;
    case I_HEAP_ADDR: value = g_heap; break;
    case I_HEAP_SIZE: value = g_heap_cap; break;
    case I_TOTAL_MEM:
    case I_TOTAL_NON_SYS: value = g_heap_cap + g_image; break;
    case I_USED_MEM:
    case I_USED_NON_SYS: value = g_heap_cur + g_image; break;
    case I_DEBUGGER_ATTACHED: value = 0; break;
    case I_RESOURCE_LIMIT: value = 0; break;
    case I_IDLE_TICK: value = ticks(); break;
    case I_RANDOM_ENTROPY: arc4random_buf(&value, sizeof value); break;
    case I_ASLR_ADDR: value = g_heap; break;
    case I_ASLR_SIZE: value = g_heap_cap; break;
    /* This is the allocation region, not just the occupied main-thread stack. */
    case I_STACK_ADDR: value = g_stack_region; break;
    case I_STACK_SIZE: value = STACK_REGION_SIZE; break;
    case I_SYS_RES_TOTAL: value = SYS_RES_TOTAL; break;
    case I_SYS_RES_USED: value = SYS_RES_USED; break;
    case I_PROGRAM_ID: value = D3_TITLE_ID; break;
    case I_INIT_PROC_ID_RANGE: value = 0; break;
    case I_USER_EXC_ADDR: value = g_exc; break;
    case I_IS_APPLICATION: value = 1; break;
    default:
    if (id > 64)
        probe_sysinfo(id, saved->x[3], (uint32_t)saved->x[30]);
    if (g_info_logs < 32)
            info("GetInfo unknown id %" PRIu64, id);
        value = 0;
        break;
    }
    if (g_info_logs < 32) {
        g_info_logs++;
        info("GetInfo id=%" PRIu64 " sub=%" PRIx64 " = %" PRIx64, id, saved->x[3], value);
    }
    set_saved(saved, 0, 0);
    set_saved(saved, 1, value);
}

/* --------------------------------------------------------------- svc batch */

static uint32_t g_batch_logs;
static uint64_t g_shared[8];
static int g_nshared;

/* The id nn::os uses as the owner of every mutex this thread takes: the SDK keeps
   it in the thread object that hangs off the thread-local region, and
   svcArbitrateUnlock has no owner argument, so the host has to read it from the
   dispatching thread. */
static uint32_t guest_thread_id(uint64_t thread_tp) {
    if (!thread_tp)
        return 0;
    const uint64_t tlr = guest_tlr_for_tp(thread_tp);
    const uint64_t thread = *(const uint64_t *)(uintptr_t)(tlr + 0x1f8);
    return thread ? *(const uint32_t *)(uintptr_t)(thread + 0x1b0) : 0;
}

static uint64_t guest_tp(void) {
    return this_guest_tls();
}

static void store64(uint64_t address, uint64_t value) {
    if (!address)
        fail("null out pointer");
    memcpy((void *)(uintptr_t)address, &value, sizeof value);
}

/* Horizon MemoryPermission: bit0 read, bit1 write, bit2 execute. */
static int host_prot(uint64_t permission) {
    int prot = 0;
    if (permission & 1)
        prot |= PROT_READ;
    if (permission & 2)
        prot |= PROT_WRITE;
    if (permission & 4)
        prot |= PROT_EXEC;
    return prot;
}

static uint64_t page_up(uint64_t size) {
    return (size + (PAGE_SIZE - 1)) & ~(uint64_t)(PAGE_SIZE - 1);
}

/* The alias region is reserved PROT_NONE; the kernel commits pages there when
   the guest maps them, so mirror that instead of handing out the whole region. */
static int in_alias(uint64_t address, uint64_t size) {
    return g_alias && size && address >= g_alias && address + size <= g_alias + g_alias_cap;
}

/* MapMemory transfers backing pages into a free stack-region range. The source
   becomes inaccessible until UnmapMemory moves those same pages back. */
static uint32_t stack_map_memory(uint64_t destination, uint64_t source, uint64_t size, int mapped) {
    d3_sync_invalidate_address_cache();
    const uint32_t invalid = 0xD401;
    uint64_t alignment = g_os_page ? g_os_page : 0x1000u;
    if (!size || ((destination | source | size) & (alignment - 1)) ||
        size > STACK_REGION_SIZE || destination < g_stack_region ||
        destination - g_stack_region > STACK_REGION_SIZE - size ||
        source > UINT64_MAX - size ||
        (source < destination + size && destination < source + size))
        return invalid;

    if (!mapped) {
        for (int i = 0; i < MAX_STACK_MAPS; i++) {
            StackMap *mapping = &g_stack_maps[i];
            if (mapping->size != size || mapping->destination != destination || mapping->source != source)
                continue;
            if (mremap((void *)(uintptr_t)destination, (size_t)size, (size_t)size,
                       MREMAP_MAYMOVE | MREMAP_FIXED, (void *)(uintptr_t)source) == MAP_FAILED)
                return invalid;
            if (mmap((void *)(uintptr_t)destination, (size_t)size, PROT_NONE,
                     MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == MAP_FAILED)
                fail("UnmapMemory lost stack reservation errno %d", errno);
            if (mprotect((void *)(uintptr_t)source, (size_t)size, host_prot(mapping->source_perm)) != 0)
                fail("UnmapMemory restore permissions errno %d", errno);
#ifdef D3_WITH_GPU
            d3_gpu_cpu_memory_permission(source, size, (mapping->source_perm & PERM_RW) == PERM_RW);
#endif
            mapping->size = 0;
            compose_regions();
            return 0;
        }
        return invalid;
    }

    Region source_region = {0};
    int found_source = 0;
    for (int i = 0; i < g_nreg; i++) {
        const Region *region = &g_reg[i];
        if (region->state != MEM_FREE && region->base < destination + size &&
            destination < region->base + region->size)
            return invalid;
        if (source >= region->base && size <= region->size &&
            source - region->base <= region->size - size &&
            (region->state == MEM_NORMAL || region->state == MEM_CODE_DATA) &&
            (region->perm & PERM_RW) == PERM_RW) {
            source_region = *region;
            found_source = 1;
        }
    }
    if (!found_source)
        return invalid;
    StackMap *mapping = NULL;
    for (int i = 0; i < MAX_STACK_MAPS; i++) {
        if (!g_stack_maps[i].size) {
            mapping = &g_stack_maps[i];
            break;
        }
    }
    if (!mapping)
        return invalid;
#ifdef D3_WITH_GPU
    d3_gpu_cpu_memory_permission(source, size, 0);
#endif
    if (mremap((void *)(uintptr_t)source, (size_t)size, (size_t)size,
               MREMAP_MAYMOVE | MREMAP_FIXED, (void *)(uintptr_t)destination) == MAP_FAILED) {
#ifdef D3_WITH_GPU
        d3_gpu_cpu_memory_permission(source, size, 1);
#endif
        return invalid;
    }
    if (mmap((void *)(uintptr_t)source, (size_t)size, PROT_NONE,
             MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == MAP_FAILED) {
        if (mremap((void *)(uintptr_t)destination, (size_t)size, (size_t)size,
                   MREMAP_MAYMOVE | MREMAP_FIXED, (void *)(uintptr_t)source) == MAP_FAILED)
            fail("MapMemory rollback failed errno %d", errno);
        if (mmap((void *)(uintptr_t)destination, (size_t)size, PROT_NONE,
                 MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == MAP_FAILED)
            fail("MapMemory rollback reservation errno %d", errno);
#ifdef D3_WITH_GPU
        d3_gpu_cpu_memory_permission(source, size, 1);
#endif
        return invalid;
    }
    *mapping = (StackMap){destination, source, size, source_region.state, source_region.perm};
    compose_regions();
    return 0;
}

static uint32_t g_alias_logs;

static void alias_commit(uint64_t address, uint64_t size, int mapped, const char *what) {
    uint64_t page = page_up(size);
    if (!address || !page)
        return;
    if (!in_alias(address, page))
        return;
#ifdef D3_WITH_GPU
    extern int d3_gpu_alias_commit(uint64_t address, uint64_t size, int mapped);
    if (d3_gpu_alias_commit(address, page, mapped) != 0)
        fail("%s GPU backing commit failed addr=%#" PRIx64 " size=%#" PRIx64, what, address, page);
#else
    if (mprotect((void *)(uintptr_t)address, (size_t)page,
                 mapped ? (PROT_READ | PROT_WRITE) : PROT_NONE) != 0) {
        info("%s mprotect(%#" PRIx64 ", %#" PRIx64 ") errno %d", what, address, page, errno);
        return;
    }
#endif
    d3_sync_invalidate_address_cache();
    if (g_alias_logs < 16) {
        g_alias_logs++;
        info("%s addr=%#" PRIx64 " size=%#" PRIx64 " %s", what, address, page,
             mapped ? "rw" : "none");
    }
}

static void range_prot(uint64_t address, uint64_t size, uint64_t permission, const char *what) {
    uint64_t page = page_up(size);
    if (!address || !page)
        return;
#ifdef D3_WITH_GPU
    d3_gpu_cpu_memory_permission(address, page, 0);
#endif
    if (mprotect((void *)(uintptr_t)address, (size_t)page, host_prot(permission)) != 0) {
        info("%s mprotect(%#" PRIx64 ", %#" PRIx64 ") errno %d", what, address, page, errno);
        return;
    }
#ifdef D3_WITH_GPU
    d3_gpu_cpu_memory_permission(address, page, (permission & PERM_RW) == PERM_RW);
#endif
    d3_sync_invalidate_address_cache();
    if (g_batch_logs < 24) {
        g_batch_logs++;
        info("%s addr=%#" PRIx64 " size=%#" PRIx64 " perm=%" PRIu64, what, address, page, permission);
    }
}

/* Shared memory is mapped straight into the caller's alias region. Single
   threaded, so the two views of one block never need to be more than the same
   anonymous mapping. */
static uint64_t map_shared_at(uint64_t address, uint64_t size, uint64_t permission) {
    uint64_t page = page_up(size);
    void *mapped;
    const int protection = host_prot(permission);
    const int seed_hid = page == 0x40000u;
    int shared_fd = -1;
    void *writer = NULL;
    if (seed_hid) {
        shared_fd = memfd_create("d3-hid", MFD_CLOEXEC);
        if (shared_fd < 0 || ftruncate(shared_fd, (off_t)page) != 0)
            fail("HID backing allocation errno %d", errno);
        writer = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE, MAP_SHARED, shared_fd, 0);
        if (writer == MAP_FAILED) fail("HID writable alias errno %d", errno);
    }
    if (!address || !page)
        fail("MapSharedMemory(%#" PRIx64 ", %#" PRIx64 ")", address, size);
    mapped = mmap((void *)(uintptr_t)address, (size_t)page,
                  protection,
                  MAP_FIXED | MAP_SHARED | (seed_hid ? 0 : MAP_ANONYMOUS), shared_fd, 0);
    if (shared_fd >= 0) close(shared_fd);
    if (mapped == MAP_FAILED)
        fail("MapSharedMemory(%#" PRIx64 ", %#" PRIx64 ") errno %d", address, page, errno);
    if ((uint64_t)(uintptr_t)mapped != address)
        fail("MapSharedMemory placed at %p", mapped);
    if (g_nshared < (int)(sizeof g_shared / sizeof g_shared[0]))
        g_shared[g_nshared++] = address;
    add_fixed(address, page, MEM_NORMAL, (uint32_t)(permission & PERM_RW));
    compose_regions();
    info("MapSharedMemory addr=%#" PRIx64 " size=%#" PRIx64 " perm=%" PRIu64, address, page,
         permission);
    /* The 256 KiB block is nn::hid's shared memory: the title reads every pad it
       believes in from there, and with the block left zeroed the engine never
       sees a controller (it relaunches the Controller applet instead of
       booting). */
    if (seed_hid) {
        d3_hid_map(address, (uint64_t)(uintptr_t)writer);
    }
    d3_sync_invalidate_address_cache();
    return address;
}

/* svcStartThread used to be bookkeeping only, so every worker the title created
   never ran.  A guest thread starts with TPIDR_EL0 = 0 exactly like the kernel
   leaves it; the title's own trampoline installs its thread pointer. */

typedef struct {
    uint64_t entry;
    uint64_t arg;
    uint64_t tls; /* the thread-local region the kernel would hand this thread */
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    int initialized;
    int exited;
} ThreadStart;

static void thread_state_init(ThreadStart *start) {
    if (start->initialized)
        return;
    pthread_condattr_t attr;
    pthread_mutex_init(&start->mutex, 0);
    pthread_condattr_init(&attr);
    pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
    pthread_cond_init(&start->cond, &attr);
    pthread_condattr_destroy(&attr);
    start->initialized = 1;
}

static void thread_mark_exited(ThreadStart *start) {
    if (start == 0)
        return;
    thread_state_init(start);
    pthread_mutex_lock(&start->mutex);
    start->exited = 1;
    pthread_cond_broadcast(&start->cond);
    pthread_mutex_unlock(&start->mutex);
}

/* A thread handle is waitable in Horizon: waiting on it means waiting for the
   thread to finish. */
static uint32_t thread_wait(ThreadStart *start, int64_t timeout_ns) {
    thread_state_init(start);
    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    if (timeout_ns > 0) {
        deadline.tv_sec += (time_t)(timeout_ns / 1000000000);
        deadline.tv_nsec += (long)(timeout_ns % 1000000000);
        if (deadline.tv_nsec >= 1000000000) {
            deadline.tv_sec++;
            deadline.tv_nsec -= 1000000000;
        }
    }
    pthread_mutex_lock(&start->mutex);
    while (!start->exited) {
        if (timeout_ns < 0) {
            pthread_cond_wait(&start->cond, &start->mutex);
            continue;
        }
        if (timeout_ns == 0 || pthread_cond_timedwait(&start->cond, &start->mutex, &deadline) != 0)
            break;
    }
    const int exited = start->exited;
    pthread_mutex_unlock(&start->mutex);
    return exited ? 0u : 0xEA01u;
}

/* bionic's pthread_self() is the pthread_internal_t, not the thread pointer: the
   veneer hands TPIDR_EL0 back to libc, so these must record the register value
   or every hook on the thread runs libc against a shuffled TLS block. */
static uint64_t host_thread_pointer(void) {
    return (uint64_t)(uintptr_t)__builtin_thread_pointer();
}

static void guest_thread_cleanup(void *argument) {
    thread_mark_exited((ThreadStart *)argument);
}

static void *guest_thread_body(void *param) {
    /* The handle keeps referring to this record, so it must outlive the thread. */
    ThreadStart *start = param;
    thread_region_assign(start->tls);
    thread_region_set_host_tp(host_thread_pointer());
    info("thread: body tid=%ld tls=%#" PRIx64, (long)gettid(), start->tls);
    log_guest_region("worker region");
    install_crash_handler();
    info("thread: start entry=%#" PRIx64 " arg=%#" PRIx64, start->entry, start->arg);
    {
        sigset_t mask;
        if (pthread_sigmask(SIG_SETMASK, 0, &mask) == 0) {
            info("thread: sigmask segv=%d bus=%d ill=%d abrt=%d", sigismember(&mask, SIGSEGV),
                 sigismember(&mask, SIGBUS), sigismember(&mask, SIGILL),
                 sigismember(&mask, SIGABRT));
        }
    }
    /* ExitThread uses pthread_exit and never returns through guest_call. */
    pthread_cleanup_push(guest_thread_cleanup, start);
    guest_call(start->entry, start->arg, 0);
    pthread_cleanup_pop(1);
    info("thread: returned");
    return 0;
}

/* Events were pure stubs: SignalEvent/ClearEvent returned success without
   changing any state and WaitSynchronization never waited, so a multi-threaded
   title could not synchronise at all.  Each event handle now owns a real
   condition variable; a successful wait consumes the signal, matching the
   auto-clear behaviour of Horizon events. */
typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    int initialized;
    int signaled;
} HostEvent;

/* One event slot per handle slot, otherwise events above 0x10FF never get a real object and waits on them silently succeed. */
#define HOST_EVENTS 0x400

static HostEvent g_events[HOST_EVENTS];
static pthread_mutex_t g_event_init = PTHREAD_MUTEX_INITIALIZER;

static HostEvent *event_of(uint32_t handle) {
    if (handle < D3_HANDLE_FIRST || handle >= D3_HANDLE_FIRST + HOST_EVENTS)
        return 0;
    HostEvent *event = &g_events[handle - D3_HANDLE_FIRST];
    pthread_mutex_lock(&g_event_init);
    if (!event->initialized) {
        pthread_condattr_t attr;
        pthread_mutex_init(&event->mutex, 0);
        pthread_condattr_init(&attr);
        pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
        pthread_cond_init(&event->cond, &attr);
        pthread_condattr_destroy(&attr);
        event->signaled = 0;
        event->initialized = 1;
    }
    pthread_mutex_unlock(&g_event_init);
    return event;
}

static void event_signal(uint32_t handle, int signaled) {
    HostEvent *event = event_of(handle);
    if (event == 0)
        return;
    pthread_mutex_lock(&event->mutex);
    event->signaled = signaled;
    if (signaled)
        pthread_cond_broadcast(&event->cond);
    pthread_mutex_unlock(&event->mutex);
}

/* The service layer hands out event handles (ICommonStateGetter::GetEventHandle)
   and has to signal them when the state the guest is waiting for actually
   changes, so the signal path needs a non-static entry point. */
void d3_event_set(uint32_t handle, int signaled) {
    event_signal(handle, signaled);
}

/* Returns 0 on success and 0xEA01 (timed out) when the deadline passes. */
/* Called when a guest closes an EVENT handle: wake waiters and mark the slot
   unusable so a reused handle slot cannot be driven by stale wait/signal paths. */
void d3_event_on_close(uint32_t handle) {
    HostEvent *event = event_of(handle);
    if (event == 0)
        return;
    pthread_mutex_lock(&event->mutex);
    event->initialized = 0;
    event->signaled = 0;
    pthread_cond_broadcast(&event->cond);
    pthread_mutex_unlock(&event->mutex);
}

static uint32_t event_wait(uint32_t handle, int64_t timeout_ns) {
    HostEvent *event = event_of(handle);
    if (event == 0)
        return 0;
    /* A level triggered event (d3_handle_set_arg(handle, 1) marks one) stays
       signalled: waiting on it never consumes the signal, which is how a service
       expresses "this condition still holds". */
    const int level = (d3_handle_arg(handle) & 1u) != 0;
    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    if (timeout_ns > 0) {
        deadline.tv_sec += (time_t)(timeout_ns / 1000000000);
        deadline.tv_nsec += (long)(timeout_ns % 1000000000);
        if (deadline.tv_nsec >= 1000000000) {
            deadline.tv_sec++;
            deadline.tv_nsec -= 1000000000;
        }
    }
    pthread_mutex_lock(&event->mutex);
    while (!event->signaled) {
        if (timeout_ns < 0) {
            pthread_cond_wait(&event->cond, &event->mutex);
            continue;
        }
        if (timeout_ns == 0 || pthread_cond_timedwait(&event->cond, &event->mutex, &deadline) != 0)
            break;
    }
    const uint32_t result = event->signaled ? 0u : 0xEA01u;
    if (event->signaled && !level)
        event->signaled = 0;
    pthread_mutex_unlock(&event->mutex);
    return result;
}

static void panic_guest(const char *what, const d3_saved *saved) {
    info("%s x0=%#" PRIx64 " x1=%#" PRIx64 " x2=%#" PRIx64 " x3=%#" PRIx64 " x4=%#" PRIx64
         " x5=%#" PRIx64 " x6=%#" PRIx64 " x7=%#" PRIx64,
         what, saved->x[0], saved->x[1], saved->x[2], saved->x[3], saved->x[4], saved->x[5],
         saved->x[6], saved->x[7]);
    uint64_t fp = saved->x[29];
    for (int depth = 0; depth < 12 && (fp & 7) == 0 && fp != 0; depth++) {
        uint64_t next = *(const uint64_t *)(uintptr_t)fp;
        uint64_t lr = *(const uint64_t *)(uintptr_t)(fp + 8);
        if (depth == 0) {
            uint64_t pc = saved->x[30];
            info("trace pc=%#" PRIx64 " (%s+%#" PRIx64 ")", pc, module_of(pc),
                 pc >= g_bias ? pc - g_bias : 0);
        }
        info("trace %d fp=%#" PRIx64 " lr=%#" PRIx64 " (%s+%#" PRIx64 ")", depth, fp, lr,
             module_of(lr), lr >= g_bias ? lr - g_bias : 0);
        if (next <= fp || next - fp > (1u << 22))
            break;
        fp = next;
    }
    d3_handle_dump();
}

/* A request on a handle the host never handed out means the guest read the
   handle out of an object that was never filled in; the SDK keeps the proxy it
   used in these image globals, so dump the pointer, the object and its vtable
   for the next run to name the class. */
void d3_watch_global(uint64_t offset, const char *why) {
    /* Expensive pointer walks belong to opt-in diagnostics, not every IPC. */
    static int enabled = -1;
    if (enabled < 0) enabled = trace_requested();
    if (!enabled) return;
    if (!g_bias)
        return;
    uint64_t pointer = 0;
    (void)safe_read(g_bias + offset, &pointer, sizeof pointer);
    static uint64_t last_pointer = ~0ull;
    static int have_last;
    static uint64_t last_words[16];
    uint64_t words[16] = {0};
    if (pointer)
        (void)safe_read(pointer, words, sizeof words);
    if (have_last && pointer == last_pointer && memcmp(words, last_words, sizeof words) == 0)
        return;
    have_last = 1;
    last_pointer = pointer;
    memcpy(last_words, words, sizeof words);
    info("watch %s global %#" PRIx64 " -> %#" PRIx64 " [%#" PRIx64 " %#" PRIx64 " %#" PRIx64
         " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 "]",
         why, offset, pointer, words[0], words[1], words[2], words[3], words[4], words[5],
         words[6], words[7]);
}

void d3_dump_sdk_global(uint64_t offset) {
    if (!g_bias) {
        info("sdk global %#" PRIx64 " without a bias", offset);
        return;
    }
    uint64_t pointer = 0;
    (void)safe_read(g_bias + offset, &pointer, sizeof pointer);
    info("sdk global %#" PRIx64 " [%#" PRIx64 "] = %#" PRIx64, offset, g_bias + offset, pointer);
    if (!pointer)
        return;
    uint64_t object[12] = {0};
    if (!safe_read(pointer, object, sizeof object)) {
        info("sdk global %#" PRIx64 ": object %#" PRIx64 " unreadable", offset, pointer);
        return;
    }
    info("sdk global %#" PRIx64 " object %#" PRIx64 ": %#" PRIx64 " %#" PRIx64 " %#" PRIx64
         " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64, offset, pointer,
         object[0], object[1], object[2], object[3], object[4], object[5], object[6], object[7]);
    uint64_t slots[8] = {0};
    if (object[0] && safe_read(object[0], slots, sizeof slots))
        info("sdk global %#" PRIx64 " vtbl %#" PRIx64 ": %#" PRIx64 " %#" PRIx64 " %#" PRIx64
             " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64 " %#" PRIx64, offset, object[0],
             slots[0], slots[1], slots[2], slots[3], slots[4], slots[5], slots[6], slots[7]);
}

void d3_trace_guest(const char *tag, const d3_saved *saved) {
    uint64_t pc = saved->x[30];
    uint64_t fp = saved->x[29];
    info("bt %s pc=%#" PRIx64 " (%s+%#" PRIx64 ")", tag, pc, module_of(pc),
         pc >= g_bias ? pc - g_bias : 0);
    /* The title's stack is not near the image (it lives megabytes below the
       mapping), so a walk that range-checks fp against g_bias never runs.  Accept
       any 8-aligned pointer in the user address space and let the monotonic
       upward-step test reject garbage; every read goes through safe_read so a
       stale fp ends the walk instead of faulting inside the svc handler. */
    for (int depth = 0; depth < 24; depth++) {
        if ((fp & 7u) != 0 || fp < 0x10000u || fp > 0x10000000000ull)
            break;
        uint64_t next = 0;
        uint64_t lr = 0;
        if (!safe_read(fp, &next, sizeof next) || !safe_read(fp + 8, &lr, sizeof lr))
            break;
        if (lr) {
            info("bt %s  #%d %s+%#" PRIx64, tag, depth, module_of(lr),
                 lr >= g_bias ? lr - g_bias : lr);
        }
        if (next <= fp || next - fp > (1u << 22))
            break;
        fp = next;
    }
}

static uint32_t g_sync_logs;
static uint32_t g_wait_logs;
static uint32_t g_tpidrro_logs;

static void svc_call(d3_saved *saved, uint32_t id, uint64_t thread_tp) {
    uint64_t *x = saved->x;
    switch (id) {
    case 0x01:
        set_heap(saved);
        return;
    case 0x02:
        range_prot(x[0], x[1], x[2], "SetMemoryPermission");
        set_saved(saved, 0, 0);
        return;
    case 0x03:
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("SetMemoryAttribute addr=%#" PRIx64 " size=%#" PRIx64 " mask=%#" PRIx64
                 " attr=%#" PRIx64, x[0], x[1], x[2], x[3]);
        }
        set_saved(saved, 0, 0);
        return;
    case 0x04:
    case 0x05: {
        uint32_t result = stack_map_memory(x[0], x[1], x[2], id == 0x04);
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("svc #%u dst=%#" PRIx64 " src=%#" PRIx64 " size=%#" PRIx64 " result=%#x", (unsigned)id, x[0],
                 x[1], x[2], result);
        }
        set_saved(saved, 0, result);
        return;
    }
    case 0x06:
        query_memory(saved);
        return;
    case 0x07:
        panic_guest("ExitProcess", saved);
        fail("guest asked to exit");
    case 0x08:
    case 0x09:
    case 0x0A:
    case 0x33:
    case 0x40:
    case 0x41:
    case 0x43:
    case 0x44:
    case 0x70:
    case 0x72:
        if (id == 0x08) {
            /* svcCreateThread(Handle* out, entry, arg, stack_top, priority, core) */
            const uint64_t out = x[0];
            ThreadStart *start = calloc(1, sizeof *start);
            if (start == 0)
                fail("CreateThread calloc");
            start->entry = x[1];
            start->arg = x[2];
            /* Horizon creates a thread-local region per thread; the title's
               thread trampoline reads it from tpidrro_el0 + 0x1f0 and installs
               it with msr tpidr_el0, so it has to be this thread's own. */
            start->tls = guest_region_alloc();
            uint32_t created = d3_handle_alloc(D3_OBJ_THREAD, "thread", (uint64_t)(uintptr_t)start);
            if (out != 0)
                *(uint32_t *)(uintptr_t)out = created;
            set_saved(saved, 0, 0);
            set_saved(saved, 1, created);
            info("CreateThread -> %#x entry=%#" PRIx64 " arg=%#" PRIx64, created, x[1], x[2]);
            return;
        }
        if (id == 0x09) {
            /* Bring-up knob: a marker file keeps StartThread inert, which lets the
               main thread run further while the thread start path is unfinished. */
            static int spawn = -1;
            if (spawn < 0) {
                char path[256];
                snprintf(path, sizeof path, "%s/notheads", D3_DATA_ROOT);
                spawn = access(path, R_OK) != 0;
                info("StartThread: spawning %s", spawn ? "enabled" : "disabled");
            }
            uint32_t handle = (uint32_t)x[0];
            if (!spawn) {
                info("StartThread handle=%#x suppressed", handle);
                set_saved(saved, 0, 0);
                return;
            }
            ThreadStart *start = (ThreadStart *)(uintptr_t)d3_handle_arg(handle);
            if (start == 0) {
                info("StartThread handle=%#x has no start record", handle);
                set_saved(saved, 0, 0);
                return;
            }
            pthread_t thread;
            if (pthread_create(&thread, 0, guest_thread_body, start) != 0)
                fail("StartThread pthread_create errno %d", errno);
            pthread_detach(thread);
            info("StartThread handle=%#x spawned", handle);
            set_saved(saved, 0, 0);
            return;
        }
        if (id == 0x0A) { /* ExitThread */
            info("ExitThread");
            pthread_exit(0);
        }
        panic_guest(id == 0x33 ? "GetThreadContext3"
                    : id == 0x40 ? "CreateSession" : id == 0x41 ? "AcceptSession"
                    : id == 0x43 ? "ReplyAndReceive" : id == 0x44 ? "ReplyAndReceiveWithUserBuffer"
                    : id == 0x70 ? "CreatePort" : "ConnectToPort", saved);
        fail("unimplemented svc #%u (phase 4b)", (unsigned)id);
    case 0x0B: {
        int64_t nanoseconds = (int64_t)x[0];
        if (nanoseconds > 0) {
            struct timespec delay;
            delay.tv_sec = nanoseconds / 1000000000;
            delay.tv_nsec = nanoseconds % 1000000000;
            (void)nanosleep(&delay, 0);
        }
        return;
    }
    case 0x0C:
        get_thread_priority(saved);
        return;
    case 0x0D:
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("SetThreadPriority handle=%#" PRIx64 " priority=%" PRIu64, x[0], x[1]);
        }
        set_saved(saved, 0, 0);
        return;
    case 0x0E:
        set_saved(saved, 0, 0);
        set_saved(saved, 1, 0);
        set_saved(saved, 2, 7);
        return;
    case 0x0F:
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("SetThreadCoreMask handle=%#" PRIx64 " core=%" PRIu64 " mask=%#" PRIx64, x[0], x[1],
                 x[2]);
        }
        set_saved(saved, 0, 0);
        return;
    case 0x10:
        set_saved(saved, 0, 0);
        return;
    case 0x11: /* SignalEvent */
    case 0x12: /* ClearEvent */
    case 0x17: /* ResetSignal */
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("svc #%u handle=%#x kind=%d", (unsigned)id, (uint32_t)x[0],
                 d3_handle_kind((uint32_t)x[0]));
        }
        event_signal((uint32_t)x[0], id == 0x11);
        set_saved(saved, 0, 0);
        return;
    case 0x13:
        map_shared_at(x[1], x[2], x[3] ? x[3] : 3);
        set_saved(saved, 0, 0);
        return;
    case 0x14:
        d3_hid_unmap(x[1]);
        range_prot(x[1], x[2], 0, "UnmapSharedMemory");
        set_saved(saved, 0, 0);
        return;
    case 0x15: {
        uint32_t created = d3_handle_alloc(D3_OBJ_TRANSFER_MEM, "trmem", x[1]);
        set_saved(saved, 0, 0);
        set_saved(saved, 1, created);
        info("CreateTransferMemory addr=%#" PRIx64 " size=%#" PRIx64 " perm=%" PRIu64
             " -> %#x", x[1], x[2], x[3], created);
        return;
    }
    case 0x16:
        if (g_batch_logs < 40) {
            g_batch_logs++;
            info("CloseHandle(%#x) kind=%d name=%s", (uint32_t)x[0],
                 d3_handle_kind((uint32_t)x[0]), d3_handle_name((uint32_t)x[0]));
        }
        if (d3_handle_close((uint32_t)x[0]) != 0 && g_batch_logs < 40) {
            g_batch_logs++;
            info("CloseHandle(%#x) unknown", (uint32_t)x[0]);
        }
        set_saved(saved, 0, 0);
        return;
    case 0x18: {
        /* svcWaitSynchronizationN(s32* out_index, Handle* handles, s32 count,
           s64 timeout).  This SDK build passes the timeout in x3 and leaves x4
           alone: every caller follows that shape (InterProcessEventImplByHorizon
           Wait passes -1, TryWait 0, MultiWaitImplByHorizon forwards its
           TimeSpan), which is why reading x4 as the timeout never matched.
           The veneer wrapper copies the returned index from x1 into *out_index,
           and the SDK then uses it to pick a MultiWait holder, so x1 must always
           carry a valid index -- leaving it as the handle pointer made
           nn::os::detail::MultiWaitImpl::InternalWaitAnyImpl index its holder
           array with 0x0be73a9c. */
        const uint64_t out_index = x[0];
        const uint64_t handles = x[1];
        const int32_t count = (int32_t)x[2];
        const int64_t timeout = (int64_t)x[3];
        enum { MAX_WAIT = 64 };
        uint32_t list[MAX_WAIT];
        const int32_t bounded = count > MAX_WAIT ? MAX_WAIT : count;
        int32_t index = 0;
        uint32_t wait_result = 0xEA01u;
        if (bounded <= 0 || handles == 0) {
            if (out_index)
                *(int32_t *)(uintptr_t)out_index = -1;
        } else {
            memcpy(list, (const void *)(uintptr_t)handles, (size_t)bounded * sizeof list[0]);
            /* Infinite waits must stay infinite: nn::os::WaitThread treats a
               fabricated timeout as fatal when loading a new scene. */
            const int64_t limit_ns = timeout < 0 ? 0 : timeout;
            const uint64_t limit_ticks = (uint64_t)limit_ns * 12u / 625u;
            const uint64_t base = ticks();
            for (;;) {
                wait_result = 0xEA01u;
                for (int32_t slot = 0; slot < bounded; slot++) {
                    const uint32_t handle = list[slot];
                    const int kind = d3_handle_kind(handle);
                    uint32_t ready = 0xEA01u;
                    if (kind == D3_OBJ_EVENT) {
                        ready = event_wait(handle, 0);
                    } else if (kind == D3_OBJ_THREAD && d3_handle_arg(handle) != 0) {
                        ready = thread_wait((ThreadStart *)(uintptr_t)d3_handle_arg(handle), 0);
                    }
                    /* Objects this host cannot wait on report ready rather than
                       leaving the SDK to index its holder array with whatever
                       was left in x1. */
                    if (ready == 0 || kind == D3_OBJ_NONE) {
                        index = slot;
                        wait_result = 0;
                        break;
                    }
                }
                if (wait_result == 0 || (timeout >= 0 && ticks() - base >= limit_ticks))
                    break;
                usleep(500);
            }
            if (wait_result == 0) {
                if (out_index)
                    *(int32_t *)(uintptr_t)out_index = index;
            } else if (out_index) {
                *(int32_t *)(uintptr_t)out_index = -1;
            }
            if (g_wait_logs < 40) {
                g_wait_logs++;
                info("WaitSynchronizationN count=%d handle=%#x name=%s timeout=%" PRId64
                     " -> result=%#x index=%d",
                     (int)count, list[0], d3_handle_name(list[0]), timeout, wait_result,
                     (int)index);
            }
        }
        set_saved(saved, 0, wait_result);
        set_saved(saved, 1, (uint64_t)(uint32_t)index);
        return;
    }
    case 0x19:
        set_saved(saved, 0, 0);
        return;
    case 0x1A: {
        uint32_t *mutex = (uint32_t *)(uintptr_t)x[1];
        if (g_sync_logs < 60) {
            g_sync_logs++;
            log_thread_id("ArbitrateLock", mutex, (uint32_t)x[2]);
        }
        set_saved(saved, 0, d3_sync_lock((uint32_t)x[0], mutex, (uint32_t)x[2]));
        return;
    }
    case 0x1B: {
        uint32_t *mutex = (uint32_t *)(uintptr_t)x[0];
        const uint32_t owner = guest_thread_id(thread_tp);
        if (g_sync_logs < 60) {
            g_sync_logs++;
            log_thread_id("ArbitrateUnlock", mutex, owner);
        }
        set_saved(saved, 0, d3_sync_unlock(mutex, owner));
        return;
    }
    case 0x1C: {
        uint32_t *mutex = (uint32_t *)(uintptr_t)x[0];
        uint32_t *key = (uint32_t *)(uintptr_t)x[1];
        uint32_t tag = (uint32_t)x[2];
        int64_t timeout = (int64_t)x[3];
        int log = g_sync_logs++ < 32;
        if (log)
            info("WaitProcessWideKeyAtomic mutex=%p key=%p tag=%#x timeout=%" PRId64,
                 (void *)mutex, (void *)key, tag, timeout);
        uint32_t result = d3_sync_wait(mutex, key, tag, timeout);
        if (log)
            info("WaitProcessWideKeyAtomic result=%#x", result);
        set_saved(saved, 0, result);
        return;
    }
    case 0x1D: {
        uint32_t result = d3_sync_signal((uint32_t *)(uintptr_t)x[0], (int32_t)x[1]);
        if (result != 0 && g_sync_logs++ < 32)
            info("SignalProcessWideKey key=%#" PRIx64 " count=%d result=%#x",
                 x[0], (int32_t)x[1], result);
        return;
    }
    case 0x1F:
        d3_svc_connect_to_named_port(saved);
        return;
    case 0x21:
        /* nn::sf::hipc::GetMessageBufferOnTls() is literally `mrs x0, tpidrro_el0`,
           so the message buffer is the thread-local region and not tpidr_el0. */
        d3_svc_send_sync_request(saved, guest_tlr_for_tp(thread_tp));
        return;
    case 0x22:
        d3_svc_send_sync_request_user(saved);
        return;
    case 0x23:
        d3_svc_send_async_request(saved);
        return;
    case 0x24:
        store64(x[0], 1);
        set_saved(saved, 0, 0);
        set_saved(saved, 1, 1);
        return;
    case 0x25:
        get_thread_id(saved);
        return;
    case 0x26:
        if (x[0] == 0) {
            if (g_batch_logs < 24) {
                g_batch_logs++;
                if (x[1] != 0 && x[2] <= 64) {
                    const uint8_t *bytes = (const uint8_t *)(uintptr_t)x[1];
                    char text[256] = {0};
                    int pos = 0;
                    for (size_t byte = 0; byte < x[2] && pos < 200; ++byte)
                        pos += snprintf(text + pos, sizeof text - (size_t)pos,
                                        "%02x ", bytes[byte]);
                    info("Break bytes %s", text);
                    char ascii[72] = {0};
                    for (size_t byte = 0; byte < x[2] && byte < 64; ++byte) {
                        unsigned char c = bytes[byte];
                        ascii[byte] = (c >= 32 && c < 127) ? (char)c : '.';
                    }
                    info("Break ascii %s", ascii);
                }
                if (x[6] > g_bias && x[6] - g_bias < (1u << 30)) {
                    const uint8_t *s = (const uint8_t *)(uintptr_t)x[6];
                    char text[200] = {0};
                    int pos = 0;
                    for (size_t byte = 0; byte < 48; ++byte) {
                        unsigned char c = s[byte];
                        if (c < 32 || c >= 127)
                            break;
                        pos += snprintf(text + pos, sizeof text - (size_t)pos, "%c", c);
                    }
                    info("Break x6 string [%s]", text);
                }
                {
                    uint64_t fp = saved->x[29];
                    for (int frame = 0; frame < 16 && fp != 0 && (fp & 7) == 0; ++frame) {
                        uint64_t next = *(const uint64_t *)(uintptr_t)fp;
                        uint64_t lr = *(const uint64_t *)(uintptr_t)(fp + 8);
                        info("brk frame %d lr=%#" PRIx64 " (%s+%#" PRIx64 ")", frame, lr,
                             module_of(lr), lr >= g_bias ? lr - g_bias : 0);
                        if (next <= fp || next - fp > (1u << 22))
                            break;
                        fp = next;
                    }
                }
                info("Break assertion reason=%" PRIu64 " arg=%#" PRIx64 " size=%" PRIu64
                    " lr=%#" PRIx64 " (%s+%#" PRIx64 ") x0=%#" PRIx64 " x1=%#" PRIx64
                    " x2=%#" PRIx64 " x3=%#" PRIx64 " x19=%#" PRIx64 " x20=%#" PRIx64
                    " x29=%#" PRIx64,
                    x[0], x[1], x[2], x[30], module_of(x[30]),
                    x[30] >= g_bias ? x[30] - g_bias : 0,
                    x[0], x[1], x[2], x[3], saved->x[19], saved->x[20],
                    saved->x[29]);
            }
            panic_guest("Break(0)", saved);
            fail("guest assertion Break(0) lr=%#" PRIx64, saved->x[30]);
        }
        info("Break reason=%" PRIu64 " arg=%#" PRIx64 " size=%" PRIu64 " lr=%#" PRIx64 " (%s+%#" PRIx64 ")",
             x[0], x[1], x[2], x[30], module_of(x[30]),
             x[30] >= g_bias ? x[30] - g_bias : 0);
        if (x[1] != 0) {
            const uint8_t *bytes = (const uint8_t *)(uintptr_t)x[1];
            size_t take = x[2] < 64 ? (size_t)x[2] : 64;
            char text[256];
            int pos = 0;
            for (size_t i = 0; i < take; i++)
                pos += snprintf(text + pos, sizeof text - (size_t)pos, "%02x ", bytes[i]);
            info("Break bytes[%s]", text);
        }
        panic_guest("Break", saved);
        return;
    case 0x27: {
        uint64_t length = x[1];
        char buffer[256];
        size_t take = length < sizeof buffer - 1 ? (size_t)length : sizeof buffer - 1;
        if (!x[0])
            fail("OutputDebugString null");
        memcpy(buffer, (const void *)(uintptr_t)x[0], take);
        buffer[take] = 0;
        for (size_t i = 0; i < take; i++) {
            if (buffer[i] == '\n' || buffer[i] == '\r')
                buffer[i] = ' ';
        }
        info("guest[%s]", buffer);
        set_saved(saved, 0, 0);
        return;
    }
    case 0x28:
        panic_guest("ReturnFromException", saved);
        fail("ReturnFromException result=%#x", (uint32_t)x[0]);
    case 0x29:
        get_info(saved);
        return;
    case 0x2A:
        set_saved(saved, 0, 10);
    case 0x2C:
    case 0x2D:
        alias_commit(x[0], x[1], id == 0x2C,
                     id == 0x2C ? "MapPhysicalMemory" : "UnmapPhysicalMemory");
        if (g_alias_logs < 16) {
            g_alias_logs++;
            info("svc #%u addr=%#" PRIx64 " size=%#" PRIx64, (unsigned)id, x[0], x[1]);
        }
        set_saved(saved, 0, 0);
        return;
    case 0x48:
    case 0x49:
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("svc #%u addr=%#" PRIx64 " size=%#" PRIx64, (unsigned)id, x[0], x[1]);
        }
        set_saved(saved, 0, 0);
        return;
    case 0x2F:
        set_saved(saved, 0, 0);
        set_saved(saved, 1, guest_tp());
        set_saved(saved, 2, 0);
        return;
    case 0x32:
        set_saved(saved, 0, 0);
        return;
    case 0x34: {
        const int log = g_sync_logs++ < 80;
        if (log)
            info("WaitForAddress addr=%#" PRIx64 " type=%u value=%d timeout=%" PRId64,
                 x[0], (uint32_t)x[1], (int32_t)x[2], (int64_t)x[3]);
        const uint32_t result = d3_sync_wait_address((uint32_t *)(uintptr_t)x[0],
                                                    (uint32_t)x[1], (int32_t)x[2], (int64_t)x[3]);
        if (log)
            info("WaitForAddress result=%#x", result);
        set_saved(saved, 0, result);
        return;
    }
    case 0x35:
        set_saved(saved, 0, d3_sync_signal_address((uint32_t *)(uintptr_t)x[0],
                                                  (uint32_t)x[1], (int32_t)x[2], (int32_t)x[3]));
        return;
    case 0x36:
        return;
    case 0x45: {
        uint32_t created = d3_handle_alloc(D3_OBJ_EVENT, "event", 0);
        set_saved(saved, 0, 0);
        set_saved(saved, 1, created);
        set_saved(saved, 2, created);
        info("CreateEvent -> %#x", created);
        return;
    }
    case 0x4B: {
        uint32_t created = d3_handle_alloc(D3_OBJ_CODE_MEM, "code", x[1]);
        set_saved(saved, 0, 0);
        set_saved(saved, 1, created);
        info("CreateCodeMemory addr=%#" PRIx64 " size=%#" PRIx64 " -> %#x", x[1], x[2], created);
        return;
    }
    case 0x50: {
        uint32_t created = d3_handle_alloc(D3_OBJ_SHARED_MEM, "shmem", x[1]);
        set_saved(saved, 0, 0);
        set_saved(saved, 1, created);
        info("CreateSharedMemory size=%#" PRIx64 " -> %#x", x[1], created);
        return;
    }
    case 0x51:
    case 0x52:
        set_saved(saved, 0, 0);
        return;
    case 0x53: {
        uint32_t created = d3_handle_alloc(D3_OBJ_EVENT, "interrupt", 0);
        set_saved(saved, 0, 0);
        set_saved(saved, 1, created);
        info("CreateInterruptEvent id=%" PRIu64 " -> %#x", x[1], created);
        return;
    }
    default:
        fail("unimplemented svc #%u x0=%#" PRIx64 " x1=%#" PRIx64 " x2=%#" PRIx64 " x3=%#"
             PRIx64, (unsigned)id, x[0], x[1], x[2], x[3]);
    }
}

static void on_tpidrro(d3_saved *saved, uint64_t extra, uint64_t thread_tp) {
    /* tpidrro_el0 names the region of the thread that is running; the veneer
       passes that thread's tpidr_el0 in x3. */
    const uint64_t tlr = guest_tlr_for_tp(thread_tp ? thread_tp : this_guest_tls());
    if (g_tpidrro_logs < 24) {
        g_tpidrro_logs++;
        info("tpidrro x%" PRIu64 " tp=%#" PRIx64 " tlr=%#" PRIx64 " [tlr+0x1f0]=%#" PRIx64,
             extra, tlr - 0x4000, tlr,
             *(const uint64_t *)(uintptr_t)(tlr + 0x1f0));
    }
    if (extra > 30)
        fail("tpidrro register %" PRIu64, extra);
    if (!tlr)
        fail("tpidrro before TLR exists");
    set_saved(saved, (uint32_t)extra, tlr);
}

/* Per id entry logs, so every syscall reports its caller once. */
static uint8_t g_seen[256];

static void dispatch_inner(uint32_t kind, uint64_t extra, d3_saved *saved, uint64_t thread_tp);

void d3_hle_dispatch(uint32_t kind, uint64_t extra, d3_saved *saved, uint64_t thread_tp) {
    /* This runs straight from guest code, so TPIDR_EL0 still points at the guest's
       TLS block.  Everything below (pthread mutexes, logging, errno, malloc) is
       host libc and needs the host thread pointer, otherwise it reads a bogus
       pthread structure and faults in bionic. */
    uint64_t guest_tp = 0;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(guest_tp));
    const uint64_t host_tp = thread_region_host_tp();
    if (host_tp)
        __asm__ volatile("msr tpidr_el0, %0" :: "r"(host_tp));
    /* Refresh the host thread pointer the hook trampolines use: the trampoline
       reads one global word, so keeping it written by the thread that is currently
       dispatching shrinks the window in which a hook runs on another thread's TLS
       from "anytime" to the few instructions of one dispatch. */
    {
        const uint64_t host_tp = thread_region_host_tp();
        if (host_tp)
            g_hook_tls.host_tp = host_tp;
    }
    dispatch_inner(kind, extra, saved, thread_tp);
    if (host_tp)
        __asm__ volatile("msr tpidr_el0, %0" :: "r"(guest_tp));
}

static void dispatch_inner(uint32_t kind, uint64_t extra, d3_saved *saved, uint64_t thread_tp) {
    g_last_kind = kind;
    g_last_extra = extra;
    if (kind == D3_KIND_SVC)
        g_svcs++;
    if (kind == D3_KIND_SVC && extra < 256) {
        if (g_seen[extra] < 6) {
            g_seen[extra]++;
            info("svc #%#x from %s+%#" PRIx64 " lr=%#" PRIx64 " x0=%#" PRIx64 " x1=%#" PRIx64
                 " x2=%#" PRIx64, (unsigned)extra, module_of(saved->x[30]),
                 saved->x[30] >= g_bias ? saved->x[30] - g_bias : 0, saved->x[30], saved->x[0],
                 saved->x[1], saved->x[2]);
        }
    }
    g_ring[g_ring_next & 15u].kind = kind;
    g_ring[g_ring_next & 15u].extra = extra;
    g_ring[g_ring_next & 15u].lr = saved->x[30];
    g_ring[g_ring_next & 15u].x0 = saved->x[0];
    g_ring_next++;
    if (g_trace_count < TRACE_MAX) {
        g_trace[g_trace_count].kind = kind;
        g_trace[g_trace_count].extra = extra;
        g_trace[g_trace_count].after = saved->x[30];
        g_trace[g_trace_count].arg0 = saved->x[0];
        g_trace_count++;
    }
    if (kind == D3_KIND_TPIDRRO) {
        on_tpidrro(saved, extra, thread_tp);
        return;
    }
    if (kind == D3_KIND_SVC) {
        svc_call(saved, (uint32_t)extra, thread_tp);
        return;
    }
    if (kind == D3_KIND_CALL) {
        if (extra == D3_CALL_EXCEPTION_STACK) {
            default_user_exception_stack(saved);
            return;
        }
        fail("unimplemented call %s extra=%" PRIu64,
             (const char *)(uintptr_t)(g_bias + D3_NAME_BASE), extra);
    }
    if (kind == D3_KIND_SYSTEM_TICK) {
        if (extra != 0)
            fail("unexpected system tick extra=%" PRIu64, extra);
        saved->x[0] = ticks();
        return;
    }
    fail("unimplemented kind %u extra=%" PRIu64, kind, extra);
}

static void guest_call_with_tp(uint64_t fn, uint64_t arg0, uint64_t arg1, uint64_t guest_tp) {
    uint64_t io[9];
    uint64_t host_tp;
    /* The guest runs with the guest TLS, so the thread's own host TLS has to be
       recorded while it is still installed: a hook (a direct branch from guest
       code) switches back to it. */
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(host_tp));
    g_hook_tls.host_tp = host_tp;
    thread_region_set_host_tp(host_tp);
    io[0] = fn;
    io[1] = arg0;
    io[2] = arg1;
    io[3] = g_guest_x18;
    io[4] = guest_tp;
    __asm__ volatile("mov %0, x18" : "=r"(io[5]));
    io[6] = host_tp;
    io[7] = 0;
    io[8] = 0;
    /* Record the *calling thread's own region*, not the pointer the guest happens
       to run on: the title re-points tpidr_el0 at its module TLS during main
       DT_INIT, and mapping that address to itself made later lookups resolve a
       thread to the title's TLS block (a fabricated thread object, so nn::os TLS
       slots read back as NULL and the critical section asserts). */
    {
        const uint64_t region = this_guest_tls();
        if (region && io[4] != region)
            tp_map_add(io[4], region);
        else if (region)
            tp_map_add(io[4], io[4]);
        if (region)
            tid_map_set((uint64_t)syscall(SYS_gettid), region);
        else
            tid_map_set((uint64_t)syscall(SYS_gettid), io[4]);
    }
    __asm__ volatile(
        "mov x19, %[io]\n"
        "ldr x9, [x19, #0]\n"
        "ldr x10, [x19, #24]\n"
        "ldr x11, [x19, #32]\n"
        "mov x18, x10\n"
        "msr tpidr_el0, x11\n"
        "ldr x0, [x19, #8]\n"
        "ldr x1, [x19, #16]\n"
        "blr x9\n"
        "mov x10, x18\n"
        "mrs x11, tpidr_el0\n"
        "str x10, [x19, #56]\n"
        "str x11, [x19, #64]\n"
        "ldr x10, [x19, #40]\n"
        "ldr x11, [x19, #48]\n"
        "mov x18, x10\n"
        "msr tpidr_el0, x11\n"
        :
        : [io] "r"(io)
        : "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
          "x12", "x13", "x14", "x15", "x16", "x17", "x19", "x30", "v0", "v1", "v2",
          "v3", "v4", "v5", "v6", "v7", "memory", "cc");
    if (io[8] != g_guest_tp)
        info("guest tp %" PRIx64 " -> %" PRIx64, g_guest_tp, io[8]);
    /* The SDK may hand the thread a TLS block of its own; keep the mapping so
       tpidrro_el0 still resolves to this thread's region. */
    tp_map_add(io[8], io[4]);
    g_guest_x18 = io[7];
    g_guest_tp = io[8];
}

static void guest_call(uint64_t fn, uint64_t arg0, uint64_t arg1) {
    guest_call_with_tp(fn, arg0, arg1, this_guest_tls());
}

static int executable(uint64_t addr) {
    for (int i = 0; i < g_nreg; i++) {
        if (addr >= g_reg[i].base && addr < g_reg[i].base + g_reg[i].size)
            return (g_reg[i].perm & PERM_X) != 0;
    }
    return 0;
}

static void call_pref(const char *name, uint64_t preferred, uint64_t arg0, uint64_t arg1) {
    uint64_t fn;
    if (!preferred) {
        info("skip %s", name);
        return;
    }
    fn = g_bias + preferred;
    if (!executable(fn))
        fail("%s address %" PRIx64 " is not executable", name, fn);
    info("call %s %" PRIx64, name, fn);
    guest_call(fn, arg0, arg1);
    info("back %s", name);
}

static void boot_sequence(void) {
    call_pref("_init_libc0", D3_SYM__init_libc0, 0, 0);
    call_pref("nnosInitialize", D3_SYM_nnosInitialize, 1, 0);
    call_pref("_init_libc1", D3_SYM__init_libc1, 0, 0);
    call_pref("nninitInitializeSdkModule", D3_SYM_nninitInitializeSdkModule, 0, 0);
    call_pref("nninitStartup", D3_SYM_nninitStartup, 0, 0);
    call_pref("_init_libc2", D3_SYM__init_libc2, 0, 0);
    /* Guest DT_INIT routines already execute their module's init arrays. */
    call_pref("sdk DT_INIT", D3_SDK_DT_INIT, 0, 0);
    call_pref("main DT_INIT", D3_MAIN_DT_INIT, 0, 0);
    call_pref("SetHostArgc", D3_SYM_SetHostArgc, 1, 0);
    call_pref("SetHostArgv", D3_SYM_SetHostArgv, (uint64_t)(uintptr_t)g_argv, 0);
    call_pref("nnMain", D3_SYM_nnMain, 0, 0);
    info("nnMain returned");
}

/* The guest can stop making SVCs and then die inside its own code, which leaves
   no host-side trace.  A periodic SIGPROF gives a poor-man's PC profile so the
   last samples show where it was executing. */

/* The handler only records into a preallocated ring: logging from a signal
   handler is not async-signal-safe.  A flusher thread prints the samples. */
#define SAMPLE_SLOTS 2048
static volatile uint64_t g_sample_pc[SAMPLE_SLOTS];
static volatile uint64_t g_sample_lr[SAMPLE_SLOTS];
static volatile uint64_t g_sample_tid[SAMPLE_SLOTS];
static volatile uint64_t g_sample_caller[SAMPLE_SLOTS];
static int g_sample_ready[SAMPLE_SLOTS];
static volatile int g_sample_count;
static int g_worker_sampling;

static void sample_handler(int sig, siginfo_t *siginfo, void *context) {
    (void)sig;
    (void)siginfo;
    const ucontext_t *state = context;
    const int slot = __atomic_fetch_add(&g_sample_count, 1, __ATOMIC_RELAXED);
    if (slot >= SAMPLE_SLOTS)
        return;
    g_sample_pc[slot] = (uint64_t)state->uc_mcontext.pc;
    g_sample_lr[slot] = (uint64_t)state->uc_mcontext.regs[30];
    g_sample_tid[slot] = (uint64_t)raw_syscall4(RAW_SYS_GETTID, 0, 0, 0, 0);
    if (g_worker_sampling) {
        uint64_t frame = (uint64_t)state->uc_mcontext.regs[29];
        for (int depth = 0; depth < 24 && frame && !(frame & 7u); depth++) {
            uint64_t words[2];
            if (!safe_read(frame, words, sizeof words))
                break;
            if (words[1] >= g_bias && words[1] - g_bias < 0x3400000u) {
                g_sample_caller[slot] = words[1] - g_bias;
                break;
            }
            if (words[0] <= frame || words[0] - frame > 0x4000000u)
                break;
            frame = words[0];
        }
    }
    __atomic_store_n(&g_sample_ready[slot], 1, __ATOMIC_RELEASE);
}

static void *sample_flusher(void *arg) {
    (void)arg;
    int printed = 0;
    for (int tick = 0; tick < (g_worker_sampling ? 1800 : 200); tick++) {
        usleep(50000);
        const int count = __atomic_load_n(&g_sample_count, __ATOMIC_ACQUIRE);
        while (printed < count && printed < SAMPLE_SLOTS &&
               __atomic_load_n(&g_sample_ready[printed], __ATOMIC_ACQUIRE)) {
            info("sample tid=%" PRIu64 " pc=%#" PRIx64 " lr=%#" PRIx64 " bias=%#" PRIx64 " guest_caller=%#" PRIx64,
                 (uint64_t)g_sample_tid[printed], (uint64_t)g_sample_pc[printed],
                 (uint64_t)g_sample_lr[printed], g_bias, (uint64_t)g_sample_caller[printed]);
            printed++;
        }
#ifdef D3_WITH_GPU
        if (g_worker_sampling && tick == 1000)
        {
            extern void d3_gpu_nv_diagnostics(void);
            d3_gpu_nv_diagnostics();
        }
#endif
    }
    return 0;
}

static void d3_host_exit_check(void) {
    __android_log_print(ANDROID_LOG_ERROR, "D3Host", "process exiting via libc exit()");
}

static void *stall_watchdog(void *arg) {
    (void)arg;
    uint64_t last = 0;
    int reports = 0;
    for (int tick = 0; tick < 40 && reports < 6; tick++) {
        usleep(500000);
        const uint64_t svcs = g_svcs;
        if (svcs != last)
            last = svcs;
        else {
            const D3Ring *entry = &g_ring[(g_ring_next - 1) & 15u];
            reports++;
            info("stall: no svc for %d ms, svcs=%" PRIu64 " last dispatch kind=%" PRIx64
                 " lr=%" PRIx64 " (%s+%#" PRIx64 ") x0=%#" PRIx64,
                 (tick + 1) * 500, svcs, entry->kind, entry->lr, module_of(entry->lr),
                 entry->lr >= g_bias ? entry->lr - g_bias : 0, entry->x0);
        }
    }
    return 0;
}

static void *guest_sampler(void *arg) {
    uint64_t tid = (uint64_t)(uintptr_t)arg;
    if (g_worker_sampling) {
        usleep(21000000);
        for (int tick = 0; tick < 40; tick++) {
            const int count = __atomic_load_n(&g_tid_map_count, __ATOMIC_ACQUIRE);
            for (int index = 0; index < count; index++)
                syscall(SYS_tgkill, getpid(), (pid_t)g_tid_map[index].tid, SIGPROF);
            usleep(100000);
        }
        return 0;
    }
    for (int tick = 0; tick < 600 && __atomic_load_n(&g_sample_count, __ATOMIC_RELAXED) < 256; tick++) {
        usleep(5000);
        syscall(SYS_tgkill, getpid(), (pid_t)tid, SIGPROF);
    }
    return 0;
}

static void *guest_thread(void *arg) {
    (void)arg;
    prctl(PR_SET_NAME, (unsigned long)"d3-guest", 0, 0, 0);
    g_guest_tid = (uint64_t)gettid();
    struct stat sample_marker;
    g_worker_sampling = stat(D3_DATA_ROOT "/sample-workers", &sample_marker) == 0;
    /* sigaltstack is per thread: without one here a stack fault cannot be reported. */
    install_crash_handler();
    {
        struct sigaction sample = {0};
        sample.sa_sigaction = sample_handler;
        sample.sa_flags = SA_SIGINFO | SA_ONSTACK;
        sigaction(SIGPROF, &sample, 0);
    }
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(g_host_tp));
    __asm__ volatile("mov %0, x18" : "=r"(g_host_x18));
    g_hook_tls.host_tp = g_host_tp;
    /* The boot thread keeps the region the guest's libc init already filled in;
       threads the guest starts get their own from guest_call. */
    thread_region_assign(g_tls);
    thread_region_set_host_tp(g_host_tp);
    g_table[D3_HOST_OFF_DISPATCH / 8] = (uint64_t)(uintptr_t)d3_hle_dispatch;
    g_table[D3_HOST_OFF_HOST_TP / 8] = g_host_tp;
    g_table[D3_HOST_OFF_GUEST_TP / 8] = g_guest_tp;
    g_table[D3_HOST_OFF_TLR / 8] = g_tlr;
    g_table[D3_HOST_OFF_MAGIC / 8] = D3_HOST_MAGIC;
    info("host tp %" PRIx64 " guest tp %" PRIx64 " tlr %" PRIx64 " bias %" PRIx64,
         g_host_tp, g_guest_tp, g_tlr, g_bias);
    {
        pthread_t sampler, flusher, watchdog;
        if (pthread_create(&flusher, 0, sample_flusher, 0) == 0)
            pthread_detach(flusher);
        if (!trace_requested() &&
            pthread_create(&sampler, 0, guest_sampler, (void *)(uintptr_t)g_guest_tid) == 0)
            pthread_detach(sampler);
        if (pthread_create(&watchdog, 0, stall_watchdog, 0) == 0)
            pthread_detach(watchdog);
    }
    register_fixed();
    if (pause_requested()) {
        info("paused for inspection, tid %" PRIu64, g_guest_tid);
        sleep(60);
    }
    if (selftest_crash()) {
        info("selftest: deliberate seal at a null pointer");
        *(volatile uint64_t *)0 = 1;
    }
    install_crash_handler();
    if (trace_requested())
        start_tracer();
    boot_sequence();
    return 0;
}

__attribute__((visibility("default")))
int d3_host_start(const char *guest_path) {
    pthread_attr_t attr;
    pthread_t thread;
    const char *path = guest_path && guest_path[0] ? guest_path : "libd3guest.so";
    if (g_started)
        return -1;
    g_started = 1;
    install_crash_handler();
    /* A silent death with no signal and no dump means the process exited through
       libc; this records that it happened even though the caller is unknown. */
    atexit(d3_host_exit_check);
    d3_service_open();
    load_guest(path);
    if (g_table[D3_HOST_OFF_MAGIC / 8] != D3_HOST_MAGIC)
        fail("host table magic %" PRIx64, g_table[D3_HOST_OFF_MAGIC / 8]);
    info("d3_host_table %p bias %" PRIx64, (void *)g_table, g_bias);
    prepare_memory();
    if (pthread_attr_init(&attr) != 0)
        fail("pthread_attr_init");
    if (pthread_attr_setstack(&attr, (void *)(uintptr_t)g_stack, STACK_SIZE) != 0)
        fail("pthread_attr_setstack");
    if (pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED) != 0)
        fail("pthread_attr_setdetachstate");
    if (pthread_create(&thread, &attr, guest_thread, 0) != 0)
        fail("pthread_create errno %d", errno);
    /* The guest runs detached: return without joining. This is an asynchronous
       JNI start, so the native call must not block the UI thread waiting for the
       guest (a return of 0 means started, not guest completion). */
    pthread_attr_destroy(&attr);
    return 0;
}
