#define _GNU_SOURCE
#include "d3_host.h"
#include "d3_service.h"
#include "d3_sync.h"
#include "../guest_layout.h"

#include <android/log.h>
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <inttypes.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
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
static uint32_t g_info_logs;
static uint64_t g_tls;
static uint64_t g_thread;
static int g_started;
static int g_regions_logged;
static int g_found_guest;
static uint32_t g_query_logs;

enum { MAX_FIXED = 40, MAX_REG = 256, MAX_STACK_MAPS = 32 };
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
static sig_atomic_t g_signal_reset[NSIG];
static pthread_once_t g_signal_once = PTHREAD_ONCE_INIT;

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

static void crash_handler(int sig, siginfo_t *si, void *context) {
    /* Only a guest fault needs its host TLS restored. Other threads must retain
       their own TLS while the preceding signal action runs. */
    const ucontext_t *uc = context;
    const mcontext_t *mc = &uc->uc_mcontext;
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
    if (known)
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

static void install_signal_actions(void) {
    static const int signals[] = {SIGSEGV, SIGBUS, SIGILL, SIGABRT, SIGFPE, SIGSYS, SIGTRAP};
    for (size_t i = 0; i < sizeof signals / sizeof signals[0]; i++) {
        int sig = signals[i];
        struct sigaction action;
        struct sigaction current;
        D3SigAction kernel;
        if (sigaction(sig, 0, &g_previous_signals[sig]) != 0)
            fail("sigaction read %d errno %d", sig, errno);
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
               fault then never reaches crash_handler.  Force the kernel slot. */
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
} D3Siginfo;

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
    t_pwrite(fd, TRACE_STATE_OFF, g_trace_state, (size_t)(p - g_trace_state));
}

static void tracer_main(pid_t target) {
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
        if (raw_syscall6(RAW_SYS_PTRACE, D3_PTRACE_ATTACH, target, 0, 0, 0, 0) == 0)
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
            t_state(fd, target, seq, (pid_t)tid, sig, event, &regs, &info);
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
    long child = raw_syscall6(RAW_SYS_CLONE, D3_SIGCHLD, 0, 0, 0, 0, 0);
    if (child == 0) {
        tracer_main(self);
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

#define D3_FS_HANDLES 32

typedef struct {
    int used;
    int fd;
    int64_t size;
} FsHandle;

static FsHandle g_fs_handles[D3_FS_HANDLES];

/* The staged game data is readable but not writable by the app, so anything the
   title creates has to live in the app's own storage; reads fall back to the
   shared copy. */
static const char *const g_guest_data_roots[] = {
    "/data/local/tmp/d3romfs",
};

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
    const char *name = guest_data_name(path);
    if (*name == 0)
        return -1;
    snprintf(out, size, "%s/%s", create ? D3_GUEST_WRITE_ROOT : g_guest_data_roots[0], name);
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
    for (int index = 0; index < D3_FS_HANDLES; index++) {
        if (g_fs_handles[index].used)
            continue;
        struct stat statbuf;
        if (fstat(fd, &statbuf) != 0) {
            close(fd);
            return -1;
        }
        g_fs_handles[index].used = 1;
        g_fs_handles[index].fd = fd;
        g_fs_handles[index].size = (int64_t)statbuf.st_size;
        info("fs: opened %s (%lld bytes) as handle %d", host, (long long)statbuf.st_size, index + 1);
        return index + 1;
    }
    close(fd);
    return -1;
}

/* nn::fs reports a missing path as MAKERESULT(2, 7); callers branch on exactly
   this value to tell "optional file absent" from a real failure. */
#define D3_FS_NOT_FOUND 0xE02u

static uint64_t hook_fs_open_file(uint64_t out, uint64_t path, uint64_t mode) {
    info("fs: OpenFile %s mode=%#" PRIx64, path ? (const char *)(uintptr_t)path : "(null)", mode);
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
    FsHandle *slot = fs_handle_of(handle);
    if (slot == 0)
        return D3_FS_NOT_FOUND;
    close(slot->fd);
    slot->used = 0;
    return 0;
}

static int64_t fs_read(uint64_t handle, int64_t offset, uint64_t buffer, uint64_t size) {
    FsHandle *slot = fs_handle_of(handle);
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
    ssize_t got = pread(slot->fd, (void *)(uintptr_t)buffer, (size_t)size, (off_t)offset);
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
    int fd = open(host, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        info("fs: create %s failed errno %d", host, errno);
        return D3_FS_NOT_FOUND;
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

/* nn::vi::native::DeserializeNativeWindow(holder, parcel, size) turns the parcel
   from CreateStrayLayer into a NativeWindow.  The real object is a binder-backed
   handle the host does not model yet, so the holder is handed a stable zeroed
   block instead: everything that later treats it as an opaque pointer keeps
   working, and the display path can be grown behind it. */
static unsigned char g_native_window[0x100];
static unsigned char g_vi_layer[0x100];

/* The real nn::vi::Layer is built from a binder-backed native window.  Handing
   the title a stable placeholder layer keeps its display code running while the
   window system stays unimplemented. */
static uint64_t hook_vi_create_layer(uint64_t out, uint64_t display, uint64_t arg2, uint64_t arg3) {
    (void)display;
    (void)arg2;
    (void)arg3;
    if (out)
        *(uint64_t *)(uintptr_t)out = (uint64_t)(uintptr_t)g_vi_layer;
    info("vi: CreateLayer -> placeholder %p", (void *)g_vi_layer);
    return 0;
}

/* A zeroed block makes the first dereference land on 0; pointing the head at the
   tail keeps a shallow chain of loads inside the block. */
static void native_window_init(void) {
    *(uint64_t *)&g_native_window[0] = (uint64_t)(uintptr_t)&g_native_window[0x40];
    *(uint64_t *)&g_native_window[0x40] = (uint64_t)(uintptr_t)&g_native_window[0x80];
}

static uint64_t hook_vi_deserialize_native_window(uint64_t holder, uint64_t parcel, uint64_t size) {
    (void)parcel;
    (void)size;
    native_window_init();
    if (holder)
        *(uint64_t *)(uintptr_t)holder = (uint64_t)(uintptr_t)g_native_window;
    info("vi: DeserializeNativeWindow -> dummy %p", (void *)g_native_window);
    return 0;
}

static uint64_t hook_vi_get_native_window(uint64_t out, uint64_t layer) {
    (void)layer;
    if (out)
        *(uint64_t *)(uintptr_t)out = (uint64_t)(uintptr_t)g_native_window;
    info("vi: GetNativeWindow -> dummy");
    return 0;
}

/* Diagnostic: the guest currently dies through std::terminate.  __cxa_throw is
   called with (object, std::type_info*, destructor) and its guest return
   address is the throw site, which is exactly what is missing from the crash
   reports.  The hook logs and stops, because a throw must not return. */
static uint64_t hook_cxa_throw(uint64_t object, uint64_t type_info, uint64_t destructor) {
    uint64_t site = (uint64_t)__builtin_return_address(0);
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
    uint64_t site = (uint64_t)__builtin_return_address(0);
    info("std::terminate caller=%#" PRIx64 " (%s+%#" PRIx64 ")", site, module_of(site),
         site >= g_bias ? site - g_bias : 0);
    abort();
    return 0;
}

static uint64_t hook_raise_exception(uint64_t exception) {
    uint64_t site = (uint64_t)__builtin_return_address(0);
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
    const char *s = (const char *)(uintptr_t)ptr;
    char text[160] = {0};
    for (int i = 0; i < 120; ++i) {
        unsigned char c = (unsigned char)s[i];
        if (c < 32 || c >= 127)
            break;
        text[i] = (char)c;
    }
    info("%s=[%s]", label, text);
}

static uint64_t hook_abort_impl(uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    log_cstr("abort arg0", a);
    log_cstr("abort arg1", b);
    log_cstr("abort arg2", c);
    log_cstr("abort arg3", d);
    abort();
    return 0;
}

static uint64_t hook_assert_failure(uint64_t type, uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    info("OnAssertionFailure type=%" PRIu64, type);
    log_cstr("assert arg1", a);
    log_cstr("assert arg2", b);
    log_cstr("assert arg3", c);
    log_cstr("assert arg4", d);
    abort();
    return 0;
}

static const GuestHook g_hooks[] = {
    {0x192600, (void *)hook_assert_failure, "nn::diag::detail::OnAssertionFailure(5 args)"},
    {0x192750, (void *)hook_assert_failure, "nn::diag::detail::OnAssertionFailure(4 args)"},
    {0x1925e0, (void *)hook_abort_impl, "nn::diag::detail::AbortImpl(f,f,f,i)"},
    {0x192500, (void *)hook_abort_impl, "nn::diag::detail::AbortImpl(f,f,f,r,f)"},
    {0x1924a0, (void *)hook_abort_impl, "nn::diag::detail::AbortImpl(f,f,f,i,r,exc,v)"},
    {0x4d9ea0, (void *)hook_cxa_throw, "__cxa_throw"},
    {0x4d72d8, (void *)hook_terminate, "std::terminate"},
    {0x532730, (void *)hook_raise_exception, "_Unwind_RaiseException"},
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
    {0x3cc020, (void *)hook_vi_deserialize_native_window, "nn::vi::native::DeserializeNativeWindow"},
    {0x3c9d10, (void *)hook_vi_get_native_window, "nn::vi::GetNativeWindow"},
    {0x3c9830, (void *)hook_vi_create_layer, "nn::vi::CreateLayer(o,d)"},
    {0x3c9880, (void *)hook_vi_create_layer, "nn::vi::CreateLayer(o,d,s)"},
    {0x3c98a0, (void *)hook_vi_create_layer, "nn::vi::CreateLayer(o,d,w,h)"},
    {0x3ca080, (void *)hook_vi_create_layer, "nn::vi::CreateLayer(o,d,f)"},
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

static void install_guest_hooks(uint64_t base, uint64_t image_size) {
    for (size_t index = 0; index < sizeof g_hooks / sizeof g_hooks[0]; index++) {
        const GuestHook *hook = &g_hooks[index];
        if (hook->vaddr + 16 > image_size)
            fail("hook %s outside image", hook->name);
        uint32_t *stub = (uint32_t *)(uintptr_t)(base + hook->vaddr);
        uint64_t target = (uint64_t)(uintptr_t)hook->target;
        stub[0] = 0x58000050u; /* ldr x16, #8 */
        stub[1] = 0xd61f0200u; /* br x16 */
        memcpy(&stub[2], &target, sizeof target);
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
    /* The image is still writable here: patch the SDK entry points before the
       segment protections go on. */
    install_guest_hooks(base, reserve_size);
    for (size_t i = 0; i < g_guest_phnum; i++) {
        if (g_guest_phdr[i].p_type == PT_LOAD)
            protect_guest_segment(base, &g_guest_phdr[i]);
    }
    g_guest = (void *)(uintptr_t)base;
    g_bias = base;
    g_image = reserve_size;
    g_table = (uint64_t *)(uintptr_t)(base + D3_HOST_TABLE);
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

static void prepare_memory(void) {
    void *tls = map_pages(PAGE_SIZE, PROT_READ | PROT_WRITE);
    void *thread = map_pages(PAGE_SIZE, PROT_READ | PROT_WRITE);
    void *tlr = map_pages(PAGE_SIZE, PROT_READ | PROT_WRITE);
    void *stack_map = map_pages(STACK_REGION_SIZE, PROT_NONE);
    g_stack_region = (uint64_t)(uintptr_t)stack_map;
    g_stack = g_stack_region + STACK_REGION_SIZE - STACK_SIZE;
    g_guard = g_stack - GUARD_SIZE;
    if (mprotect((void *)(uintptr_t)g_stack, STACK_SIZE, PROT_READ | PROT_WRITE) != 0)
        fail("stack mprotect errno %d", errno);
    g_tls = (uint64_t)(uintptr_t)tls;
    g_thread = (uint64_t)(uintptr_t)thread;
    g_tlr = (uint64_t)(uintptr_t)tlr;
    g_guest_tp = g_tls;
    *(uint16_t *)(uintptr_t)(g_tlr + 0x100) = 0;
    *(uint16_t *)(uintptr_t)(g_tlr + 0x102) = 0;
    *(uint64_t *)(uintptr_t)(g_tlr + 0x1f0) = g_tls;
    *(uint64_t *)(uintptr_t)(g_tlr + 0x1f8) = g_thread;
    struct timespec boot;
    /* nn::os::detail::AddressRegionManager (the VAMM the sdk builds from the
       GetInfo alias region) commits its bookkeeping page and every later
       allocation with MapPhysicalMemory, so the region itself is reserved
       PROT_NONE and gets read/write pages on demand (alias_commit). */
    void *alias = mmap(0, (size_t)ALIAS_SIZE, PROT_NONE,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
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
    } else if (page < g_heap_cur) {
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

static void get_thread_id(d3_saved *saved) {
    uint64_t id = D3_THREAD_ID;
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

static uint64_t guest_tp(void) {
    return g_table[D3_HOST_OFF_GUEST_TP / 8];
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
    if (mremap((void *)(uintptr_t)source, (size_t)size, (size_t)size,
               MREMAP_MAYMOVE | MREMAP_FIXED, (void *)(uintptr_t)destination) == MAP_FAILED)
        return invalid;
    if (mmap((void *)(uintptr_t)source, (size_t)size, PROT_NONE,
             MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == MAP_FAILED) {
        if (mremap((void *)(uintptr_t)destination, (size_t)size, (size_t)size,
                   MREMAP_MAYMOVE | MREMAP_FIXED, (void *)(uintptr_t)source) == MAP_FAILED)
            fail("MapMemory rollback failed errno %d", errno);
        if (mmap((void *)(uintptr_t)destination, (size_t)size, PROT_NONE,
                 MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) == MAP_FAILED)
            fail("MapMemory rollback reservation errno %d", errno);
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
    if (mprotect((void *)(uintptr_t)address, (size_t)page,
                 mapped ? (PROT_READ | PROT_WRITE) : PROT_NONE) != 0) {
        info("%s mprotect(%#" PRIx64 ", %#" PRIx64 ") errno %d", what, address, page, errno);
        return;
    }
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
    if (mprotect((void *)(uintptr_t)address, (size_t)page, host_prot(permission)) != 0) {
        info("%s mprotect(%#" PRIx64 ", %#" PRIx64 ") errno %d", what, address, page, errno);
        return;
    }
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
    if (!address || !page)
        fail("MapSharedMemory(%#" PRIx64 ", %#" PRIx64 ")", address, size);
    mapped = mmap((void *)(uintptr_t)address, (size_t)page, host_prot(permission),
                  MAP_FIXED | MAP_SHARED | MAP_ANONYMOUS, -1, 0);
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
    return address;
}

/* svcStartThread used to be bookkeeping only, so every worker the title created
   never ran.  A guest thread starts with TPIDR_EL0 = 0 exactly like the kernel
   leaves it; the title's own trampoline installs its thread pointer. */
static void guest_call(uint64_t fn, uint64_t arg0, uint64_t arg1);

typedef struct {
    uint64_t entry;
    uint64_t arg;
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

static void *guest_thread_body(void *param) {
    /* The handle keeps referring to this record, so it must outlive the thread. */
    ThreadStart *start = param;
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
    guest_call(start->entry, start->arg, 0);
    thread_mark_exited(start);
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

#define HOST_EVENTS 256

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

/* Returns 0 on success and 0xEA01 (timed out) when the deadline passes. */
static uint32_t event_wait(uint32_t handle, int64_t timeout_ns) {
    HostEvent *event = event_of(handle);
    if (event == 0)
        return 0;
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
    if (event->signaled)
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

void d3_trace_guest(const char *tag, const d3_saved *saved) {
    uint64_t pc = saved->x[30];
    uint64_t fp = saved->x[29];
    info("bt %s pc=%#" PRIx64 " (%s+%#" PRIx64 ")", tag, pc, module_of(pc),
         pc >= g_bias ? pc - g_bias : 0);
    for (int depth = 0; depth < 20 && (fp & 7) == 0; depth++) {
        if (fp < g_bias - 0x100000 || fp > g_bias + 0x40000000u)
            break;
        uint64_t next = *(const uint64_t *)(uintptr_t)fp;
        uint64_t lr = *(const uint64_t *)(uintptr_t)(fp + 8);
        if (lr >= g_bias)
            info("bt %s  #%d %s+%#" PRIx64, tag, depth, module_of(lr), lr - g_bias);
        if (next <= fp || next - fp > (1u << 22))
            break;
        fp = next;
    }
}

static uint32_t g_sync_logs;

static void svc_call(d3_saved *saved, uint32_t id) {
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
        /* Single handle form is (handle, timeout); the N form passes a list. */
        if (x[0] >= D3_HANDLE_FIRST && x[0] < D3_HANDLE_FIRST + HOST_EVENTS) {
            const uint32_t handle = (uint32_t)x[0];
            uint32_t result;
            if (d3_handle_kind(handle) == D3_OBJ_THREAD)
                result = thread_wait((ThreadStart *)(uintptr_t)d3_handle_arg(handle), (int64_t)x[1]);
            else
                result = event_wait(handle, (int64_t)x[1]);
            if (g_batch_logs < 32) {
                g_batch_logs++;
                info("WaitSynchronization handle=%#x timeout=%" PRId64 " -> %#x", handle,
                     (int64_t)x[1], result);
            }
            set_saved(saved, 0, result);
            set_saved(saved, 1, 0);
            return;
        }
        /* svcWaitSynchronizationN(s32* out_index, Handle* handles, s32 count,
           bool wait_all, s64 timeout).  The SDK returns *out_index verbatim when
           the result is zero, so it must never be left uninitialised. */
        uint64_t list = x[1];
        int32_t count = (int32_t)x[2];
        uint32_t first = 0xFFFFFFFFu;
        if (list && count > 0)
            memcpy(&first, (const void *)(uintptr_t)list, sizeof first);
        if (count <= 0) {
            if (x[0])
                *(int32_t *)(uintptr_t)x[0] = -1;
            if (g_batch_logs < 32) {
                g_batch_logs++;
                info("WaitSynchronizationN count=%d -> timed out", count);
            }
            set_saved(saved, 0, (uint64_t)-1);
            return;
        }
        if (x[0])
            *(int32_t *)(uintptr_t)x[0] = 0;
        /* Wait for real: nn::os builds its MultiWait bookkeeping from this
           result.  x3 is wait_all (bool); the timeout is x4.  An infinite
           timeout is capped so a missing signal stalls briefly instead of
           hanging the app. */
        /* Skip thread handles here: their object pointers are sometimes stale
           (fault 0x300 came from a bogus ThreadStart).  Only events are waited. */
        if (first != 0xFFFFFFFFu && d3_handle_kind(first) == D3_OBJ_EVENT) {
            int64_t wait_timeout = (int64_t)x[4];
            if (wait_timeout < 0)
                wait_timeout = 2000000;
            uint32_t wait_result;
            if (d3_handle_kind(first) == D3_OBJ_THREAD && d3_handle_arg(first) != 0) {
                wait_result = thread_wait(
                    (ThreadStart *)(uintptr_t)d3_handle_arg(first), wait_timeout);
            } else {
                wait_result = event_wait(first, wait_timeout);
            }
            if (wait_result != 0) {
                /* The SDK indexes its holder array with the value returned in
                   w0 (disassembly at sdk+0x335d38: mov w24, w0).  Handing back
                   0xEA01 makes that index 59905 and walks off the stack, so a
                   timeout is reported as "the first object was ready" until the
                   holder bookkeeping itself is modelled. */
                if (x[0])
                    *(int32_t *)(uintptr_t)x[0] = 0;
                set_saved(saved, 0, 0);
                return;
            }
        }
        set_saved(saved, 0, 0);
        if (g_batch_logs < 32) {
            g_batch_logs++;
            info("WaitSynchronizationN count=%d handle=%#x name=%s timeout=%" PRId64 " -> index 0",
                 count, first, d3_handle_name(first), (int64_t)x[4]);
        }
        return;
    }
    case 0x19:
        set_saved(saved, 0, 0);
        return;
    case 0x1A:
        set_saved(saved, 0, d3_sync_lock((uint32_t)x[0], (uint32_t *)(uintptr_t)x[1],
                                       (uint32_t)x[2]));
        return;
    case 0x1B:
        set_saved(saved, 0, d3_sync_unlock((uint32_t *)(uintptr_t)x[0],
                                         (uint32_t)D3_THREAD_ID));
        return;
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
        d3_svc_send_sync_request(saved, g_table[D3_HOST_OFF_TLR / 8]);
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
    case 0x34:
    case 0x35:
        if (g_batch_logs < 24) {
            g_batch_logs++;
            info("svc #%u addr=%#" PRIx64 " x1=%#" PRIx64 " x2=%#" PRIx64 " x3=%#" PRIx64,
                 (unsigned)id, x[0], x[1], x[2], x[3]);
        }
        set_saved(saved, 0, 0);
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

static void on_tpidrro(d3_saved *saved, uint64_t extra) {
    uint64_t tlr = g_table[D3_HOST_OFF_TLR / 8];
    if (extra > 30)
        fail("tpidrro register %" PRIu64, extra);
    if (!tlr)
        fail("tpidrro before TLR exists");
    set_saved(saved, (uint32_t)extra, tlr);
}

/* Per id entry logs, so every syscall reports its caller once. */
static uint8_t g_seen[256];

void d3_hle_dispatch(uint32_t kind, uint64_t extra, d3_saved *saved) {
    __asm__ volatile("mov x18, %0" :: "r"(g_host_x18) : "memory");
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
        on_tpidrro(saved, extra);
        return;
    }
    if (kind == D3_KIND_SVC) {
        svc_call(saved, (uint32_t)extra);
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

static void guest_call(uint64_t fn, uint64_t arg0, uint64_t arg1) {
    uint64_t io[9];
    io[0] = fn;
    io[1] = arg0;
    io[2] = arg1;
    io[3] = g_guest_x18;
    io[4] = g_guest_tp;
    io[5] = g_host_x18;
    io[6] = g_host_tp;
    io[7] = 0;
    io[8] = 0;
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
    g_guest_x18 = io[7];
    g_guest_tp = io[8];
    g_table[D3_HOST_OFF_GUEST_TP / 8] = g_guest_tp;
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
#define SAMPLE_SLOTS 256
static volatile uint64_t g_sample_pc[SAMPLE_SLOTS];
static volatile int g_sample_count;

static void sample_handler(int sig, siginfo_t *siginfo, void *context) {
    (void)sig;
    (void)siginfo;
    const ucontext_t *state = context;
    const int slot = g_sample_count;
    if (slot >= SAMPLE_SLOTS)
        return;
    g_sample_pc[slot] = (uint64_t)state->uc_mcontext.pc;
    g_sample_count = slot + 1;
}

static void *sample_flusher(void *arg) {
    (void)arg;
    int printed = 0;
    for (int tick = 0; tick < 200; tick++) {
        usleep(50000);
        const int count = g_sample_count;
        while (printed < count && printed < SAMPLE_SLOTS) {
            info("sample pc=%#" PRIx64, (uint64_t)g_sample_pc[printed]);
            printed++;
        }
    }
    return 0;
}

static void d3_host_exit_check(void) {
    __android_log_print(ANDROID_LOG_ERROR, "D3Host", "process exiting via libc exit()");
}

static void *guest_sampler(void *arg) {
    uint64_t tid = (uint64_t)(uintptr_t)arg;
    for (int tick = 0; tick < 600 && g_sample_count < SAMPLE_SLOTS; tick++) {
        usleep(5000);
        syscall(SYS_tgkill, getpid(), (pid_t)tid, SIGPROF);
    }
    return 0;
}

static void *guest_thread(void *arg) {
    (void)arg;
    prctl(PR_SET_NAME, (unsigned long)"d3-guest", 0, 0, 0);
    g_guest_tid = (uint64_t)gettid();
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
    g_table[D3_HOST_OFF_DISPATCH / 8] = (uint64_t)(uintptr_t)d3_hle_dispatch;
    g_table[D3_HOST_OFF_HOST_TP / 8] = g_host_tp;
    g_table[D3_HOST_OFF_GUEST_TP / 8] = g_guest_tp;
    g_table[D3_HOST_OFF_TLR / 8] = g_tlr;
    g_table[D3_HOST_OFF_MAGIC / 8] = D3_HOST_MAGIC;
    info("host tp %" PRIx64 " guest tp %" PRIx64 " tlr %" PRIx64 " bias %" PRIx64,
         g_host_tp, g_guest_tp, g_tlr, g_bias);
    {
        pthread_t sampler, flusher;
        if (pthread_create(&flusher, 0, sample_flusher, 0) == 0)
            pthread_detach(flusher);
        if (pthread_create(&sampler, 0, guest_sampler, (void *)(uintptr_t)g_guest_tid) == 0)
            pthread_detach(sampler);
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
    if (trace_requested())
        start_tracer();
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
