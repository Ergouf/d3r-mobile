#include "../host/d3_host.c"

extern void d3_test_guest_roundtrip(void);
extern void d3_test_guest_counter(void);
extern void d3_test_guest_vibration(void);

typedef struct {
    uint64_t result;
    uint64_t before;
    uint64_t after;
    uint64_t x18;
    uint64_t argument;
    uint64_t padding;
    uint64_t q16[2];
    uint64_t q31[2];
} GuestRoundtrip;

typedef struct {
    uint64_t region;
    int failed;
} GuestWorker;

static pthread_barrier_t g_worker_barrier;

static void *exercise_guest_tls(void *argument) {
    GuestWorker *worker = argument;
    const uint64_t host_tp = host_thread_pointer();
    uint64_t host_x18;
    __asm__ volatile("mov %0, x18" : "=r"(host_x18));
    worker->region = this_guest_tls();
    thread_region_set_host_tp(host_tp);
    pthread_barrier_wait(&g_worker_barrier);
    for (int iteration = 0; iteration < 1000; iteration++) {
        GuestRoundtrip roundtrip = {0};
        guest_call_with_tp((uint64_t)(uintptr_t)d3_test_guest_roundtrip,
                           g_bias + 0x341c40u, (uint64_t)(uintptr_t)&roundtrip, worker->region);
        uint64_t actual_x18;
        __asm__ volatile("mov %0, x18" : "=r"(actual_x18));
        if (roundtrip.result != worker->region + GUEST_THREAD_OFFSET ||
            roundtrip.before != worker->region || roundtrip.after != worker->region ||
            roundtrip.x18 != worker->region || roundtrip.q16[0] != worker->region ||
            roundtrip.q16[1] != worker->region || roundtrip.q31[0] != worker->region ||
            roundtrip.q31[1] != worker->region || host_thread_pointer() != host_tp ||
            actual_x18 != host_x18 || current_guest_region() != worker->region + GUEST_TLR_OFFSET) {
            worker->failed = 1;
            break;
        }
        guest_call_with_tp((uint64_t)(uintptr_t)d3_test_guest_roundtrip,
                           g_bias + 0x341f40u, (uint64_t)(uintptr_t)&roundtrip, worker->region);
        __asm__ volatile("mov %0, x18" : "=r"(actual_x18));
        if (roundtrip.before != worker->region || roundtrip.after != worker->region ||
            roundtrip.x18 != worker->region || host_thread_pointer() != host_tp ||
            actual_x18 != host_x18) {
            worker->failed = 1;
            break;
        }
    }
    return NULL;
}

int main(int count, char **arguments) {
    alarm(25);
    if (count != 2)
        return 2;
    load_guest(arguments[1]);
    if (*(const uint32_t *)(uintptr_t)(g_bias + 0x3499b0u) != 0xb00035a0u)
        return 1;
    if (*(const uint32_t *)(uintptr_t)(g_bias + 0x532730u) != 0xf0003830u ||
        *(const uint32_t *)(uintptr_t)(g_bias + 0x3cc020u) != 0xd10283ffu ||
        *(const uint32_t *)(uintptr_t)(g_bias + 0x3c9830u) != 0xd100c3ffu ||
        *(const uint32_t *)(uintptr_t)(g_bias + 0x3c9d10u) != 0xf81d0ff5u)
        return 1;
    GuestWorker workers[4] = {0};
    pthread_t threads[4];
    if (pthread_barrier_init(&g_worker_barrier, NULL, 4) != 0)
        return 1;
    for (int index = 0; index < 4; index++) {
        if (pthread_create(&threads[index], NULL, exercise_guest_tls, &workers[index]) != 0)
            return 1;
    }
    for (int index = 0; index < 4; index++) {
        if (pthread_join(threads[index], NULL) != 0 || workers[index].failed) {
            fprintf(stderr, "FAIL: guest TLS worker %d\n", index);
            return 1;
        }
        for (int previous = 0; previous < index; previous++) {
            if (workers[index].region == workers[previous].region)
                return 1;
        }
    }
    const uint64_t region = this_guest_tls();
    static uint8_t hid_block[0x40000];
    d3_hid_seed((uint64_t)(uintptr_t)hid_block);
    uint32_t style;
    memcpy(&style, hid_block + 0x9a00, sizeof style);
    if (style != 1 || (style & (style - 1)))
        return 1;
    uint32_t vibration_handles[2] = {0};
    uint32_t vibration_count = 0;
    struct {
        uint64_t target;
        uint64_t handles;
        uint64_t count;
        uint32_t capacity;
        uint32_t npad;
        uint32_t style;
        uint32_t padding;
    } vibration_request = {g_bias + 0x258ef0u, (uint64_t)(uintptr_t)vibration_handles,
                            (uint64_t)(uintptr_t)&vibration_count, 2, 0, style, 0};
    GuestRoundtrip vibration = {0};
    vibration.argument = (uint64_t)(uintptr_t)&vibration_request;
    guest_call_with_tp((uint64_t)(uintptr_t)d3_test_guest_roundtrip,
                       (uint64_t)(uintptr_t)d3_test_guest_vibration,
                       (uint64_t)(uintptr_t)&vibration, region);
    if (vibration.result || vibration_count != 2 || vibration_handles[0] != 3 ||
        vibration_handles[1] != 0x10003)
        return 1;
    puts("PASS: original guest vibration enumerator accepts the seeded single FullKey style");
    install_crash_handler();
    GuestRoundtrip counter = {0};
    guest_call_with_tp((uint64_t)(uintptr_t)d3_test_guest_roundtrip,
                       (uint64_t)(uintptr_t)d3_test_guest_counter, (uint64_t)(uintptr_t)&counter, region);
    if (!counter.result || counter.before != region || counter.after != region || counter.x18 != region)
        return 1;
    char filename[] = "/data/local/tmp/d3romfs/d3-native-exists-XXXXXX";
    const int descriptor = mkstemp(filename);
    if (descriptor < 0)
        return 1;
    close(descriptor);
    char guest_name[256];
    snprintf(guest_name, sizeof guest_name, "data:/%s", strrchr(filename, '/') + 1);
    uint32_t metadata[16] = {0};
    uint64_t request[5] = {0, (uint64_t)(uintptr_t)guest_name, 0, 0,
                            (uint64_t)(uintptr_t)metadata};
    GuestRoundtrip existence = {0};
    existence.argument = (uint64_t)(uintptr_t)request;
    guest_call_with_tp((uint64_t)(uintptr_t)d3_test_guest_roundtrip,
                       g_bias + 0x1002230u, (uint64_t)(uintptr_t)&existence, region);
    if (existence.result != 1 || metadata[14] != 1 || unlink(filename) != 0)
        return 1;
    guest_call_with_tp((uint64_t)(uintptr_t)d3_test_guest_roundtrip,
                       g_bias + 0x1002230u, (uint64_t)(uintptr_t)&existence, region);
    if (existence.result != 1 || metadata[14] != 0) {
        fprintf(stderr, "FAIL: guest existence result for missing file = %llu\n",
                (unsigned long long)existence.result);
        return 1;
    }
    puts("PASS: four threads each preserve guest/host TP and x18 across 1000 real SDK veneer and hook calls");
    puts("PASS: original game file-existence code distinguishes existing and missing files");
    return 0;
}
