#define _GNU_SOURCE
#include "d3_sync.h"
#include "d3_service.h"
#ifdef D3_WITH_GPU
#include "../gpu/host/gpu_bridge.h"
#endif

#include <android/log.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static uint32_t g_sync_logs;
#define sync_log(fmt, ...) do { \
    if (__atomic_fetch_add(&g_sync_logs, 1, __ATOMIC_RELAXED) < 256) \
        __android_log_print(ANDROID_LOG_INFO, "D3Host", fmt, ##__VA_ARGS__); \
} while (0)

enum {
    SYNC_INVALID_ADDRESS = 0xcc01,
    SYNC_OUT_OF_RESOURCE = 0xce01,
    SYNC_INVALID_MEMORY = 0xd401,
    SYNC_INVALID_HANDLE = 0xe401,
    SYNC_INVALID_ENUM = 0xf001,
    SYNC_INVALID_STATE = 0xfa01,
    WAIT_DONE = 0,
    WAIT_MUTEX = 1,
    WAIT_KEY = 2,
    WAIT_ADDRESS = 3
};

typedef struct SyncWaiter {
    struct SyncWaiter *next;
    uint32_t *mutex;
    uint32_t *key;
    uint32_t tag;
    uint32_t result;
    int state;
    pthread_cond_t ready;
} SyncWaiter;

static pthread_mutex_t g_sync_lock = PTHREAD_MUTEX_INITIALIZER;
static SyncWaiter *g_sync_waiters;
static pthread_mutex_t g_address_cache_lock = PTHREAD_MUTEX_INITIALIZER;
static int g_address_cache_enabled;
static uint64_t g_address_cache_epoch;
static uint32_t g_address_cache_next;
static struct {
    uintptr_t start;
    uintptr_t end;
    int writable;
} g_address_cache[128];

void d3_sync_invalidate_address_cache(void) {
    pthread_mutex_lock(&g_address_cache_lock);
    memset(g_address_cache, 0, sizeof g_address_cache);
    g_address_cache_next = 0;
    g_address_cache_epoch++;
    pthread_mutex_unlock(&g_address_cache_lock);
}

void d3_sync_enable_address_cache(int enabled) {
    d3_sync_invalidate_address_cache();
    __atomic_store_n(&g_address_cache_enabled, enabled != 0, __ATOMIC_RELEASE);
}

static uint32_t sync_address_access(uint32_t *word, int writable) {
    uintptr_t address = (uintptr_t)word;
    if (address & 3u)
        return SYNC_INVALID_ADDRESS;
    if (!address || address > UINTPTR_MAX - sizeof *word)
        return SYNC_INVALID_MEMORY;
#ifdef D3_WITH_GPU
    if (d3_gpu_cpu_memory_writable(address)) return 0;
#endif
    const int cache_enabled = __atomic_load_n(&g_address_cache_enabled, __ATOMIC_ACQUIRE);
    uint64_t epoch = 0;
    if (cache_enabled) {
        pthread_mutex_lock(&g_address_cache_lock);
        epoch = g_address_cache_epoch;
        for (size_t index = 0; index < 128; index++) {
            if (address >= g_address_cache[index].start &&
                address + sizeof *word <= g_address_cache[index].end &&
                (!writable || g_address_cache[index].writable)) {
                pthread_mutex_unlock(&g_address_cache_lock);
                return 0;
            }
        }
        pthread_mutex_unlock(&g_address_cache_lock);
    }
    FILE *maps = fopen("/proc/self/maps", "re");
    if (!maps)
        return SYNC_INVALID_MEMORY;
    char line[512];
    uint32_t result = SYNC_INVALID_MEMORY;
    while (fgets(line, sizeof line, maps)) {
        uintptr_t start, end;
        char permissions[5];
        if (sscanf(line, "%" SCNxPTR "-%" SCNxPTR " %4s", &start, &end, permissions) != 3)
            continue;
        if (address >= start && address + sizeof *word <= end) {
            if (permissions[0] == 'r' && (!writable || permissions[1] == 'w')) {
                result = 0;
                if (cache_enabled) {
                    pthread_mutex_lock(&g_address_cache_lock);
                    if (epoch == g_address_cache_epoch) {
                        const uint32_t slot = g_address_cache_next++ % 128;
                        g_address_cache[slot].start = start;
                        g_address_cache[slot].end = end;
                        g_address_cache[slot].writable = permissions[1] == 'w';
                    }
                    pthread_mutex_unlock(&g_address_cache_lock);
                }
            }
            break;
        }
    }
    fclose(maps);
    return result;
}

static uint32_t sync_address(uint32_t *word) {
    return sync_address_access(word, 1);
}

static int sync_tag(uint32_t tag) {
    return tag && !(tag & UINT32_C(0xc0000000));
}

static int sync_owner(uint32_t tag) {
    return tag == 1u || d3_handle_kind(tag) == D3_OBJ_THREAD;
}

static uint32_t sync_waiter_init(SyncWaiter *waiter, uint32_t *mutex, uint32_t *key,
                                 uint32_t tag, int state) {
    memset(waiter, 0, sizeof *waiter);
    waiter->mutex = mutex;
    waiter->key = key;
    waiter->tag = tag;
    waiter->state = state;
    pthread_condattr_t attr;
    if (pthread_condattr_init(&attr) != 0)
        return SYNC_OUT_OF_RESOURCE;
    int result = pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
    if (result == 0)
        result = pthread_cond_init(&waiter->ready, &attr);
    pthread_condattr_destroy(&attr);
    return result == 0 ? 0 : SYNC_OUT_OF_RESOURCE;
}

static void sync_append(SyncWaiter *waiter) {
    SyncWaiter **end = &g_sync_waiters;
    while (*end)
        end = &(*end)->next;
    waiter->next = 0;
    *end = waiter;
}

static void sync_remove(SyncWaiter *waiter) {
    SyncWaiter **entry = &g_sync_waiters;
    while (*entry && *entry != waiter)
        entry = &(*entry)->next;
    if (*entry)
        *entry = waiter->next;
    waiter->next = 0;
}

static void sync_finish(SyncWaiter *waiter, uint32_t result) {
    sync_remove(waiter);
    waiter->result = result;
    waiter->state = WAIT_DONE;
    pthread_cond_signal(&waiter->ready);
}

static void sync_unlock_locked(uint32_t *mutex) {
    SyncWaiter *next_owner = 0;
    int more = 0;
    for (SyncWaiter *waiter = g_sync_waiters; waiter; waiter = waiter->next) {
        if (waiter->state != WAIT_MUTEX || waiter->mutex != mutex)
            continue;
        if (!next_owner)
            next_owner = waiter;
        else
            more = 1;
    }
    uint32_t value = next_owner ? next_owner->tag : 0;
    if (more)
        value |= D3_SYNC_WAIT_MASK;
    __atomic_store_n(mutex, value, __ATOMIC_RELEASE);
    if (next_owner)
        sync_finish(next_owner, 0);
}

static uint32_t sync_sleep(SyncWaiter *waiter, const struct timespec *deadline) {
    while (waiter->state != WAIT_DONE) {
        int result = deadline
                   ? pthread_cond_timedwait(&waiter->ready, &g_sync_lock, deadline)
                   : pthread_cond_wait(&waiter->ready, &g_sync_lock);
        if (waiter->state == WAIT_DONE)
            break;
        if (result != 0) {
            sync_remove(waiter);
            waiter->result = result == ETIMEDOUT ? D3_SYNC_TIMED_OUT : SYNC_INVALID_STATE;
            waiter->state = WAIT_DONE;
        }
    }
    return waiter->result;
}

uint32_t d3_sync_lock(uint32_t owner, uint32_t *mutex, uint32_t tag) {
    uint32_t result = sync_address(mutex);
    if (result != 0)
        return result;
    if (!sync_tag(tag))
        return SYNC_INVALID_HANDLE;
    SyncWaiter waiter;
    result = sync_waiter_init(&waiter, mutex, 0, tag, WAIT_MUTEX);
    if (result != 0)
        return result;
    pthread_mutex_lock(&g_sync_lock);
    /* Only a take by the thread that already owns the mutex may return without
       waiting, and the caller's identity is `tag` (the value nn::os writes into
       every lock word it owns).  `owner` is only what the caller read out of the
       word -- the *current* owner, which for a second thread is someone else, so
       comparing against it made a contended take look recursive and both threads
       believed they held the same SDK mutex. */
    const uint32_t value = __atomic_load_n(mutex, __ATOMIC_ACQUIRE);
    if (value != (owner | D3_SYNC_WAIT_MASK)) {
        result = 0;
    } else if (!sync_owner(owner)) {
        result = SYNC_INVALID_HANDLE;
    } else {
        /* Horizon signals "there are waiters" with the WAIT bit, and the unlocker's
           *fast* path in guest code checks that bit: when it is clear the fast path
           just stores zero and never comes back through svcArbitrateUnlock.  Setting
           the bit here is what makes the release reach sync_unlock_locked (without
           it a contended mutex slept forever, which is where nninitStartup's
           nn::os::LockMutex call stalled). */
        sync_log("sync: lock %p tag=%u owner=%u blocks", (void *)mutex, tag, owner);
        sync_append(&waiter);
        result = sync_sleep(&waiter, 0);
        sync_log("sync: lock %p woke result=%#x", (void *)mutex, result);
    }
    pthread_mutex_unlock(&g_sync_lock);
    pthread_cond_destroy(&waiter.ready);
    return result;
}

uint32_t d3_sync_unlock(uint32_t *mutex, uint32_t tag) {
    uint32_t result = sync_address(mutex);
    if (result != 0)
        return result;
    if (!sync_tag(tag))
        return SYNC_INVALID_HANDLE;
    pthread_mutex_lock(&g_sync_lock);
    sync_log("sync: unlock %p tag=%u", (void *)mutex, tag);
    /* svcArbitrateUnlock never fails on hardware: it releases the word whatever it
       currently holds and hands it to the first waiter.  The SDK aborts when the
       call reports an error, and the title legitimately releases locks it does not
       own (the thread-start mutex is taken by the new thread and released by its
       parent), so a mismatched owner must still be a successful release. */
    if ((__atomic_load_n(mutex, __ATOMIC_ACQUIRE) & ~D3_SYNC_WAIT_MASK) != tag) {
        const uint32_t word = __atomic_load_n(mutex, __ATOMIC_ACQUIRE);
        sync_log("sync: unlock %p owner mismatch word=%#x tag=%u", (void *)mutex, word, tag);
        pthread_mutex_unlock(&g_sync_lock);
        return SYNC_INVALID_STATE;
    }
    sync_unlock_locked(mutex);
    pthread_mutex_unlock(&g_sync_lock);
    return 0;
}

uint32_t d3_sync_wait(uint32_t *mutex, uint32_t *key, uint32_t tag, int64_t timeout) {
    uint32_t result = sync_address(mutex);
    if (result == 0)
        result = sync_address(key);
    if (result != 0)
        return result;
    if (!sync_tag(tag))
        return SYNC_INVALID_HANDLE;
    struct timespec deadline;
    if (timeout >= 0) {
        if (clock_gettime(CLOCK_MONOTONIC, &deadline) != 0)
            return SYNC_INVALID_STATE;
        deadline.tv_sec += timeout / INT64_C(1000000000);
        deadline.tv_nsec += (long)(timeout % INT64_C(1000000000));
        if (deadline.tv_nsec >= 1000000000L) {
            deadline.tv_nsec -= 1000000000L;
            deadline.tv_sec++;
        }
    }
    SyncWaiter waiter;
    result = sync_waiter_init(&waiter, mutex, key, tag, WAIT_KEY);
    if (result != 0)
        return result;
    pthread_mutex_lock(&g_sync_lock);
    if ((__atomic_load_n(mutex, __ATOMIC_ACQUIRE) & ~D3_SYNC_WAIT_MASK) != tag) {
        result = SYNC_INVALID_STATE;
    } else {
        __atomic_store_n(key, 1u, __ATOMIC_RELEASE);
        sync_unlock_locked(mutex);
        if (timeout == 0) {
            result = D3_SYNC_TIMED_OUT;
        } else {
            sync_log("sync: wait %p blocks timeout=%" PRId64, (void *)key, timeout);
            sync_append(&waiter);
            /* Horizon leaves the mutex unowned on timeout. The SDK reacquires it. */
            result = sync_sleep(&waiter, timeout < 0 ? 0 : &deadline);
            sync_log("sync: wait %p woke result=%#x", (void *)key, result);
        }
    }
    pthread_mutex_unlock(&g_sync_lock);
    pthread_cond_destroy(&waiter.ready);
    return result;
}

static void sync_reacquire(SyncWaiter *waiter) {
    uint32_t result = sync_address(waiter->mutex);
    if (result != 0) {
        sync_finish(waiter, result);
        return;
    }
    uint32_t previous = __atomic_load_n(waiter->mutex, __ATOMIC_ACQUIRE);
    for (;;) {
        uint32_t desired = previous ? previous | D3_SYNC_WAIT_MASK : waiter->tag;
        if (__atomic_compare_exchange_n(waiter->mutex, &previous, desired, 0,
                                        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
            break;
    }
    if (previous == 0) {
        sync_finish(waiter, 0);
    } else if (!sync_owner(previous & ~D3_SYNC_WAIT_MASK)) {
        sync_finish(waiter, SYNC_INVALID_STATE);
    } else {
        sync_remove(waiter);
        waiter->state = WAIT_MUTEX;
        sync_append(waiter);
    }
}

uint32_t d3_sync_signal(uint32_t *key, int32_t count) {
    uint32_t result = sync_address(key);
    if (result != 0)
        return result;
    pthread_mutex_lock(&g_sync_lock);
    int signaled = 0;
    SyncWaiter *waiter = g_sync_waiters;
    while (waiter && (count <= 0 || signaled < count)) {
        SyncWaiter *next = waiter->next;
        if (waiter->state == WAIT_KEY && waiter->key == key) {
            sync_reacquire(waiter);
            signaled++;
        }
        waiter = next;
    }
    int remaining = 0;
    for (waiter = g_sync_waiters; waiter; waiter = waiter->next) {
        if (waiter->state == WAIT_KEY && waiter->key == key) {
            remaining = 1;
            break;
        }
    }
    __atomic_store_n(key, (uint32_t)remaining, __ATOMIC_RELEASE);
    pthread_mutex_unlock(&g_sync_lock);
    return 0;
}

uint32_t d3_sync_wait_address(uint32_t *address, uint32_t type, int32_t value, int64_t timeout) {
    if (type > 2)
        return SYNC_INVALID_ENUM;
    uint32_t result = sync_address_access(address, type == 1);
    if (result != 0)
        return result;
    struct timespec deadline;
    if (timeout > 0) {
        if (clock_gettime(CLOCK_MONOTONIC, &deadline) != 0)
            return SYNC_INVALID_STATE;
        deadline.tv_sec += timeout / INT64_C(1000000000);
        deadline.tv_nsec += (long)(timeout % INT64_C(1000000000));
        if (deadline.tv_nsec >= 1000000000L) {
            deadline.tv_nsec -= 1000000000L;
            deadline.tv_sec++;
        }
    }
    SyncWaiter waiter;
    result = sync_waiter_init(&waiter, 0, address, 0, WAIT_ADDRESS);
    if (result != 0)
        return result;
    pthread_mutex_lock(&g_sync_lock);
    uint32_t observed = __atomic_load_n(address, __ATOMIC_ACQUIRE);
    for (;;) {
        if (type == 2 ? (int32_t)observed != value : (int32_t)observed >= value) {
            result = SYNC_INVALID_STATE;
            break;
        }
        if (type == 1 && !__atomic_compare_exchange_n(address, &observed, observed - 1u, 0,
                                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
            continue;
        if (timeout == 0) {
            result = D3_SYNC_TIMED_OUT;
        } else {
            sync_append(&waiter);
            result = sync_sleep(&waiter, timeout < 0 ? 0 : &deadline);
        }
        break;
    }
    pthread_mutex_unlock(&g_sync_lock);
    pthread_cond_destroy(&waiter.ready);
    return result;
}

uint32_t d3_sync_signal_address(uint32_t *address, uint32_t type, int32_t value, int32_t count) {
    if (type > 2)
        return SYNC_INVALID_ENUM;
    uint32_t result = sync_address_access(address, type != 0);
    if (result != 0)
        return result;
    pthread_mutex_lock(&g_sync_lock);
    int waiting = 0;
    for (SyncWaiter *waiter = g_sync_waiters; waiter; waiter = waiter->next) {
        if (waiter->state == WAIT_ADDRESS && waiter->key == address)
            waiting++;
    }
    if (type != 0) {
        uint32_t desired = (uint32_t)value + 1u;
        if (type == 2 && waiting != 0) {
            desired = count <= 0 ? (uint32_t)value - 2u
                                : waiting <= count ? (uint32_t)value - 1u : (uint32_t)value;
        }
        uint32_t observed = (uint32_t)value;
        if (!__atomic_compare_exchange_n(address, &observed, desired, 0,
                                         __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
            result = SYNC_INVALID_STATE;
    }
    if (result == 0) {
        int signaled = 0;
        SyncWaiter *waiter = g_sync_waiters;
        while (waiter && (count <= 0 || signaled < count)) {
            SyncWaiter *next = waiter->next;
            if (waiter->state == WAIT_ADDRESS && waiter->key == address) {
                sync_finish(waiter, 0);
                signaled++;
            }
            waiter = next;
        }
    }
    pthread_mutex_unlock(&g_sync_lock);
    return result;
}
