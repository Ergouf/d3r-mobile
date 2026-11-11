/* Concurrent memory SVCs must not expose a partially rebuilt/sorted table. */
#ifndef D3_MEMORY_TEST_HOST
#define D3_MEMORY_TEST_HOST "../host/d3_host.c"
#endif
#define __android_log_vprint memory_test_log
#include D3_MEMORY_TEST_HOST
#undef __android_log_vprint

int memory_test_log(int priority, const char* tag, const char* format, va_list arguments) {
    (void)tag;
    if (priority >= ANDROID_LOG_ERROR) {
        vfprintf(stderr, format, arguments);
        fputc('\n', stderr);
    }
    return 0;
}

enum { WRITERS = 4, PER_WRITER = 32, ROUNDS = 6, REGION_STRIDE = 2 * PAGE_SIZE };
static pthread_barrier_t start_barrier;
static uint64_t arena;
static unsigned finished, failed;

static void* map_pages_worker(void* argument) {
    const unsigned writer = (unsigned)(uintptr_t)argument;
    pthread_barrier_wait(&start_barrier);
    for (unsigned n = 0; n < PER_WRITER; ++n) {
        const unsigned slot = n * WRITERS + writer;
        d3_saved saved = {0};
        saved.x[1] = arena + slot * REGION_STRIDE;
        saved.x[2] = PAGE_SIZE;
        saved.x[3] = PERM_RW;
        svc_call(&saved, 0x13, 0);
        if (saved.x[0]) __atomic_store_n(&failed, 1, __ATOMIC_RELAXED);
    }
    __atomic_fetch_add(&finished, 1, __ATOMIC_RELEASE);
    return NULL;
}

static void* query_pages_worker(void* unused) {
    (void)unused;
    pthread_barrier_wait(&start_barrier);
    unsigned sequence = 0;
    do {
        const uint64_t address = arena + (sequence++ % (WRITERS * PER_WRITER)) * REGION_STRIDE;
        MemInfo memory = {0};
        d3_saved saved = {0};
        saved.x[0] = (uint64_t)(uintptr_t)&memory;
        saved.x[2] = address;
        svc_call(&saved, 0x06, 0);
        if (saved.x[0] || memory.addr > address || !memory.size ||
            address - memory.addr >= memory.size ||
            (memory.state != MEM_FREE && (memory.state != MEM_NORMAL || memory.perm != PERM_RW)))
            __atomic_store_n(&failed, 1, __ATOMIC_RELAXED);
    } while (__atomic_load_n(&finished, __ATOMIC_ACQUIRE) < WRITERS);
    return NULL;
}

int main(void) {
    g_os_page = (size_t)sysconf(_SC_PAGESIZE);
    if (g_os_page != 4096) return 77;
    for (unsigned round = 0; round < ROUNDS; ++round) {
        const size_t bytes = WRITERS * PER_WRITER * REGION_STRIDE;
        void* reservation = mmap(NULL, bytes, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (reservation == MAP_FAILED) return 2;
        arena = (uint64_t)(uintptr_t)reservation;
        g_nfixed = g_nreg = g_nshared = 0;
        finished = failed = 0;
        memset(g_stack_maps, 0, sizeof g_stack_maps);
        if (pthread_barrier_init(&start_barrier, NULL, WRITERS + 1)) return 3;
        pthread_t writers[WRITERS], reader;
        for (unsigned i = 0; i < WRITERS; ++i)
            if (pthread_create(&writers[i], NULL, map_pages_worker, (void*)(uintptr_t)i)) return 4;
        if (pthread_create(&reader, NULL, query_pages_worker, NULL)) return 5;
        for (unsigned i = 0; i < WRITERS; ++i) pthread_join(writers[i], NULL);
        pthread_join(reader, NULL);
        pthread_barrier_destroy(&start_barrier);
        if (failed || g_nfixed != WRITERS * PER_WRITER || g_nreg != WRITERS * PER_WRITER) return 6;
        for (unsigned i = 0; i < WRITERS * PER_WRITER; ++i) {
            if (g_reg[i].base != arena + i * REGION_STRIDE || g_reg[i].size != PAGE_SIZE) return 7;
        }
        if (munmap(reservation, bytes)) return 8;
    }
    puts("PASS: 768 concurrent shared mappings, coherent QueryMemory and sorted region publication");
    return 0;
}
