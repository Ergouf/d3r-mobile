#include "../host/d3_host.c"
#include "../host/d3_sync.c"

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

typedef struct {
    uint32_t *address;
    uint32_t type;
    int32_t value;
    int64_t timeout;
    uint32_t result;
    int done;
} AddressWait;

static void *address_wait_thread(void *argument) {
    AddressWait *wait = argument;
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)wait->address;
    saved.x[1] = wait->type;
    saved.x[2] = (uint32_t)wait->value;
    saved.x[3] = (uint64_t)wait->timeout;
    svc_call(&saved, 0x34, 0);
    wait->result = (uint32_t)saved.x[0];
    __atomic_store_n(&wait->done, 1, __ATOMIC_RELEASE);
    return NULL;
}

static int await_waiters(uint32_t *address, int expected) {
    for (int attempt = 0; attempt < 500; attempt++) {
        int count = 0;
        pthread_mutex_lock(&g_sync_lock);
        for (SyncWaiter *waiter = g_sync_waiters; waiter; waiter = waiter->next) {
            if (waiter->state == WAIT_ADDRESS && waiter->key == address)
                count++;
        }
        pthread_mutex_unlock(&g_sync_lock);
        if (count == expected)
            return 0;
        struct timespec pause = {0, 1000000};
        nanosleep(&pause, NULL);
    }
    return 1;
}

static uint32_t signal_svc(uint32_t *address, uint32_t type, int32_t value, int32_t count) {
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)address;
    saved.x[1] = type;
    saved.x[2] = (uint32_t)value;
    saved.x[3] = (uint32_t)count;
    svc_call(&saved, 0x35, 0);
    return (uint32_t)saved.x[0];
}

static int predicates_and_errors(void) {
    uint32_t address = 1;
    CHECK(d3_sync_wait_address(&address, 2, 2, 0) == SYNC_INVALID_STATE);
    CHECK(d3_sync_wait_address(&address, 2, 1, 0) == D3_SYNC_TIMED_OUT);
    CHECK(d3_sync_wait_address(&address, 0, 2, 0) == D3_SYNC_TIMED_OUT);
    CHECK(address == 1);
    CHECK(d3_sync_wait_address(&address, 0, 1, 0) == SYNC_INVALID_STATE);
    CHECK(d3_sync_wait_address(&address, 1, 1, 0) == SYNC_INVALID_STATE);
    CHECK(address == 1);
    address = UINT32_MAX;
    CHECK(d3_sync_wait_address(&address, 1, 0, 0) == D3_SYNC_TIMED_OUT);
    CHECK(address == UINT32_MAX - 1u);
    CHECK(d3_sync_wait_address(&address, 0, -3, 0) == SYNC_INVALID_STATE);
    CHECK(signal_svc(&address, 1, 1, 0) == SYNC_INVALID_STATE);
    CHECK(address == UINT32_MAX - 1u);
    CHECK(signal_svc(&address, 1, -2, 0) == 0);
    CHECK(address == UINT32_MAX);
    CHECK(signal_svc(&address, 2, -1, 0) == 0);
    CHECK(address == 0);
    CHECK(d3_sync_wait_address(&address, 3, 0, 0) == SYNC_INVALID_ENUM);
    CHECK(signal_svc(&address, 3, 0, 0) == SYNC_INVALID_ENUM);
    CHECK(d3_sync_wait_address((uint32_t *)((uintptr_t)&address + 1), 2, 0, 0)
          == SYNC_INVALID_ADDRESS);
    CHECK(signal_svc(NULL, 1, 0, 0) == SYNC_INVALID_MEMORY);
    void *readonly = mmap(NULL, 4096, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(readonly != MAP_FAILED);
    CHECK(d3_sync_wait_address(readonly, 2, 0, 0) == D3_SYNC_TIMED_OUT);
    CHECK(d3_sync_wait_address(readonly, 1, 1, 0) == SYNC_INVALID_MEMORY);
    CHECK(signal_svc(readonly, 1, 0, 0) == SYNC_INVALID_MEMORY);
    CHECK(munmap(readonly, 4096) == 0);
    struct timespec start, end;
    CHECK(clock_gettime(CLOCK_MONOTONIC, &start) == 0);
    CHECK(d3_sync_wait_address(&address, 2, 0, 20000000) == D3_SYNC_TIMED_OUT);
    CHECK(clock_gettime(CLOCK_MONOTONIC, &end) == 0);
    CHECK((end.tv_sec - start.tv_sec) * INT64_C(1000000000)
          + end.tv_nsec - start.tv_nsec >= 10000000);
    CHECK(await_waiters(&address, 0) == 0);
    return 0;
}

static int wake_counts(uint32_t type, int32_t count) {
    uint32_t address = 1;
    uint32_t other = 1;
    AddressWait waits[3] = {
        {&address, 2, 1, 1000000000, 0, 0},
        {&address, 2, 1, 1000000000, 0, 0},
        {&other, 2, 1, 1000000000, 0, 0}
    };
    pthread_t threads[3];
    for (int index = 0; index < 3; index++)
        CHECK(pthread_create(&threads[index], NULL, address_wait_thread, &waits[index]) == 0);
    CHECK(await_waiters(&address, 2) == 0);
    CHECK(await_waiters(&other, 1) == 0);
    CHECK(signal_svc(&address, type, 0, count) == (type == 0 ? 0u : SYNC_INVALID_STATE));
    if (type != 0)
        CHECK(await_waiters(&address, 2) == 0);
    if (type == 0) {
        if (count == 1)
            CHECK(await_waiters(&address, 1) == 0);
        else
            CHECK(await_waiters(&address, 0) == 0);
    } else {
        CHECK(signal_svc(&address, type, 1, count) == 0);
        CHECK(await_waiters(&address, count > 0 && count < 2 ? 1 : 0) == 0);
        CHECK(address == (type == 1 ? 2u : count <= 0 ? UINT32_MAX : count < 2 ? 1u : 0u));
    }
    CHECK(!__atomic_load_n(&waits[2].done, __ATOMIC_ACQUIRE));
    CHECK(signal_svc(&address, 0, 0, 0) == 0);
    CHECK(signal_svc(&other, 0, 0, 0) == 0);
    for (int index = 0; index < 3; index++) {
        CHECK(pthread_join(threads[index], NULL) == 0);
        CHECK(waits[index].result == 0);
    }
    return 0;
}

static int light_event_race(void) {
    for (int round = 0; round < 100; round++) {
        uint32_t address = 1;
        AddressWait wait = {&address, 2, 1, 1000000000, 0, 0};
        pthread_t thread;
        CHECK(pthread_create(&thread, NULL, address_wait_thread, &wait) == 0);
        if (round & 1)
            CHECK(await_waiters(&address, 1) == 0);
        __atomic_store_n(&address, 2, __ATOMIC_RELEASE);
        CHECK(signal_svc(&address, 0, 0, -1) == 0);
        CHECK(pthread_join(thread, NULL) == 0);
        CHECK(wait.result == 0 || wait.result == SYNC_INVALID_STATE);
    }
    uint32_t address = 1;
    AddressWait wait = {&address, 2, 1, -1, 0, 0};
    pthread_t thread;
    CHECK(pthread_create(&thread, NULL, address_wait_thread, &wait) == 0);
    CHECK(await_waiters(&address, 1) == 0);
    CHECK(signal_svc(&address, 0, 0, -1) == 0);
    CHECK(pthread_join(thread, NULL) == 0);
    CHECK(wait.result == 0);
    return 0;
}

int main(void) {
    alarm(15);
    CHECK(predicates_and_errors() == 0);
    for (uint32_t type = 0; type < 3; type++) {
        CHECK(wake_counts(type, 1) == 0);
        CHECK(wake_counts(type, 2) == 0);
        CHECK(wake_counts(type, 0) == 0);
        CHECK(wake_counts(type, -1) == 0);
    }
    CHECK(light_event_race() == 0);
    puts("PASS: address arbitration predicates, timeouts, wake counts, atomic updates, races and SVC ABI");
    return 0;
}
