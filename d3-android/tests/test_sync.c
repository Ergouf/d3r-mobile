/* Android-native unit test for the standalone sync module (host/d3_sync.c).

   The module is a pthread implementation of the guest sync syscalls, now wired
   into the host SVC table (0x1A-0x1D) and the host build. It is driven here
   through its public API (black box) and through the real SVC dispatch, against
   the Horizon protocol it must keep:

     d3_sync_lock(owner, mutex, tag)    ArbitrateLock
     d3_sync_unlock(mutex, tag)         Unlock
     d3_sync_wait(mutex, key, tag, ns)  WaitProcessWideKeyAtomic
     d3_sync_signal(key, count)         SignalProcessWideKey

   Pinned contract:
     - lock: a word that is not (owner | 0x40000000) returns 0 and does not touch
       the word; a matching word with a live thread owner blocks until the holder
       hands the lock over, and the woken waiter then owns the word under its own
       tag. A matching word whose owner is not a thread handle is 0xe401.
     - wait: releases the mutex, then waits on key; on success the caller owns the
       mutex again. A timeout returns 0xea01 and leaves the mutex released (the
       SDK reacquires it); a negative timeout waits forever. The key waiter hint
       is 1 while a wait is outstanding, and may stay 1 after a timeout; signal
       clears it once no waiter on that key remains.
     - signal: count <= 0 wakes every waiter, otherwise up to count; a woken
       waiter only succeeds once it has reacquired the mutex, so a signal sent
       while the mutex is held elsewhere does not complete the wait early.
     - rejected arguments: unaligned word 0xcc01, unreadable/unwritable word
       0xd401, bad owner tag 0xe401 -- never a fabricated 0.

   Every case runs on a worker thread behind a bounded parent timeout, so a bug
   fails the test instead of hanging it. This module is a standalone pthread
   implementation; it is not the guest scheduler and this test does not claim
   multi-threaded guest bridging.

   It includes the host translation unit for the real d3_trace_guest and the
   real SVC dispatch table, plus the sync module it drives; d3_service.c (handle
   table) is the only object it links. */
#include "../host/d3_host.c"
#include "../host/d3_sync.c"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

#define MAIN_TAG UINT32_C(1)
#define WAIT_MASK D3_SYNC_WAIT_MASK
#define TIMED_OUT D3_SYNC_TIMED_OUT
#define SENTINEL UINT32_C(0x5a5a5a5a)

/* Result codes the module returns for a rejected argument. */
#define RES_INVALID_ADDRESS UINT32_C(0xcc01)
#define RES_INVALID_MEMORY UINT32_C(0xd401)
#define RES_INVALID_HANDLE UINT32_C(0xe401)
#define RES_INVALID_STATE UINT32_C(0xfa01)

#define CASE_LIMIT_MS 4000
#define RACE_ROUNDS 100

/* A statement that survives -Wempty-body and stops the compiler from hoisting
   an atomic load out of a spin loop. */
#define SPIN_BARRIER() __atomic_signal_fence(__ATOMIC_ACQUIRE)

static uint32_t g_worker_tag;
static uint32_t g_worker2_tag;

static void msleep(int ms) {
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}

static int64_t ns_since(const struct timespec *start) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (int64_t)(now.tv_sec - start->tv_sec) * INT64_C(1000000000)
         + (int64_t)(now.tv_nsec - start->tv_nsec);
}

/* Runs one case body on a worker thread and bounds it with a parent timeout, so
   a stuck wait fails the test rather than hanging the process. */
typedef struct Case {
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int finished;
    int ok;
    int (*body)(void);
} Case;

static void case_finish(Case *c, int ok) {
    pthread_mutex_lock(&c->lock);
    c->ok = ok;
    c->finished = 1;
    pthread_cond_broadcast(&c->cond);
    pthread_mutex_unlock(&c->lock);
}

static void *case_thread(void *arg) {
    Case *c = arg;
    case_finish(c, c->body());
    return NULL;
}

/* 0 once body() returned (its value in *out), else -1 on timeout. */
static int run_case(int (*body)(void), int *out) {
    Case c;
    memset(&c, 0, sizeof c);
    c.body = body;
    if (pthread_mutex_init(&c.lock, NULL) != 0)
        return -1;
    pthread_condattr_t attr;
    if (pthread_condattr_init(&attr) != 0)
        return -1;
    (void)pthread_condattr_setclock(&attr, CLOCK_MONOTONIC);
    int init = pthread_cond_init(&c.cond, &attr);
    pthread_condattr_destroy(&attr);
    if (init != 0)
        return -1;

    pthread_t thread;
    if (pthread_create(&thread, NULL, case_thread, &c) != 0)
        return -1;

    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    deadline.tv_sec += CASE_LIMIT_MS / 1000;
    deadline.tv_nsec += (long)(CASE_LIMIT_MS % 1000) * 1000000L;
    if (deadline.tv_nsec >= 1000000000L) {
        deadline.tv_nsec -= 1000000000L;
        deadline.tv_sec++;
    }

    pthread_mutex_lock(&c.lock);
    while (!c.finished) {
        if (pthread_cond_timedwait(&c.cond, &c.lock, &deadline) == ETIMEDOUT &&
            !c.finished) {
            pthread_mutex_unlock(&c.lock);
            return -1; /* the body is stuck; the process exits shortly */
        }
    }
    int ok = c.ok;
    pthread_mutex_unlock(&c.lock);
    pthread_join(thread, NULL);
    pthread_cond_destroy(&c.cond);
    pthread_mutex_destroy(&c.lock);
    *out = ok;
    return 0;
}

/* Wait-side worker: runs one d3_sync_wait and records its result. */
typedef struct WaitArg {
    uint32_t *mutex;
    uint32_t *key;
    uint32_t tag;
    int64_t timeout;
    uint32_t rc;
    volatile int done;
} WaitArg;

static void *wait_thread(void *arg) {
    WaitArg *a = arg;
    a->rc = d3_sync_wait(a->mutex, a->key, a->tag, a->timeout);
    __atomic_store_n(&a->done, 1, __ATOMIC_RELEASE);
    return NULL;
}

/* Lock-side worker: ArbitrateLock, then read the owned word and Unlock. */
typedef struct HoArg {
    uint32_t owner;
    uint32_t tag;
    uint32_t *mutex;
    uint32_t lock_rc;
    uint32_t held;
    uint32_t unlock_rc;
    volatile int entered;
} HoArg;

static void *ho_waiter(void *arg) {
    HoArg *a = arg;
    __atomic_store_n(&a->entered, 1, __ATOMIC_RELEASE);
    a->lock_rc = d3_sync_lock(a->owner, a->mutex, a->tag);
    a->held = __atomic_load_n(a->mutex, __ATOMIC_ACQUIRE);
    a->unlock_rc = d3_sync_unlock(a->mutex, a->tag);
    return NULL;
}

static void wait_arg_init(WaitArg *a, uint32_t *mutex, uint32_t *key,
                          uint32_t tag, int64_t timeout) {
    memset(a, 0, sizeof *a);
    a->mutex = mutex;
    a->key = key;
    a->tag = tag;
    a->timeout = timeout;
    a->rc = SENTINEL;
}

static void ho_arg_init(HoArg *a, uint32_t owner, uint32_t tag, uint32_t *mutex) {
    memset(a, 0, sizeof *a);
    a->owner = owner;
    a->tag = tag;
    a->mutex = mutex;
    a->lock_rc = a->held = a->unlock_rc = SENTINEL;
}

/* 1. An unaligned word is 0xcc01 and is rejected before it is touched. */
static int case_alignment(void) {
    static uint32_t word;
    uint32_t *misaligned = (uint32_t *)(void *)((uint8_t *)&word + 1);
    word = MAIN_TAG;
    CHECK(d3_sync_lock(MAIN_TAG, misaligned, MAIN_TAG) == RES_INVALID_ADDRESS);
    CHECK(d3_sync_unlock(misaligned, MAIN_TAG) == RES_INVALID_ADDRESS);
    CHECK(d3_sync_wait(misaligned, &word, MAIN_TAG, 0) == RES_INVALID_ADDRESS);
    CHECK(d3_sync_wait(&word, misaligned, MAIN_TAG, 0) == RES_INVALID_ADDRESS);
    CHECK(d3_sync_signal(misaligned, 1) == RES_INVALID_ADDRESS);
    CHECK(word == MAIN_TAG);
    return 0;
}

/* 2. A word that is NULL, unmapped, or not writable is 0xd401 (never 0). */
static int case_invalid_memory(void) {
    static uint32_t word;
    word = MAIN_TAG;
    CHECK(d3_sync_lock(MAIN_TAG, NULL, MAIN_TAG) == RES_INVALID_MEMORY);
    CHECK(d3_sync_wait(&word, NULL, MAIN_TAG, 0) == RES_INVALID_MEMORY);
    CHECK(d3_sync_signal(NULL, 1) == RES_INVALID_MEMORY);

    void *none = mmap(NULL, 0x1000, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(none != MAP_FAILED);
    uint32_t *unmapped = none;
    CHECK(d3_sync_lock(MAIN_TAG, unmapped, MAIN_TAG) == RES_INVALID_MEMORY);
    CHECK(d3_sync_unlock(unmapped, MAIN_TAG) == RES_INVALID_MEMORY);
    CHECK(d3_sync_wait(unmapped, unmapped, MAIN_TAG, 0) == RES_INVALID_MEMORY);
    CHECK(d3_sync_signal(unmapped, 1) == RES_INVALID_MEMORY);

    void *ro = mmap(NULL, 0x1000, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(ro != MAP_FAILED);
    uint32_t *readonly = ro;
    CHECK(d3_sync_lock(MAIN_TAG, readonly, MAIN_TAG) == RES_INVALID_MEMORY);

    CHECK(word == MAIN_TAG);
    CHECK(munmap(none, 0x1000) == 0);
    CHECK(munmap(ro, 0x1000) == 0);
    return 0;
}

/* 3. lock: 0 when the word is not (owner | mask); 0xe401 only when it matches a
   word whose owner is not a live thread handle, or when the waiter tag is bad. */
static int case_invalid_owner(void) {
    static uint32_t word;

    word = UINT32_C(0x12345678);
    CHECK(d3_sync_lock(MAIN_TAG, &word, MAIN_TAG) == 0);
    CHECK(d3_sync_lock(g_worker_tag, &word, g_worker_tag) == 0);
    CHECK(word == UINT32_C(0x12345678)); /* allowed, but not acquired */

    word = WAIT_MASK; /* matches owner 0 */
    CHECK(d3_sync_lock(0, &word, MAIN_TAG) == RES_INVALID_HANDLE);
    word = UINT32_C(0x7ffffff0); /* matches a handle with no live object */
    CHECK(d3_sync_lock(UINT32_C(0x7ffffff0), &word, MAIN_TAG) == RES_INVALID_HANDLE);
    CHECK(word == UINT32_C(0x7ffffff0)); /* rejected, not consumed */

    word = MAIN_TAG;
    CHECK(d3_sync_lock(MAIN_TAG, &word, 0) == RES_INVALID_HANDLE);
    CHECK(d3_sync_lock(MAIN_TAG, &word, UINT32_C(0x80000000)) == RES_INVALID_HANDLE);
    return 0;
}

/* 4. unlock only releases the word when the tag is its owner. */
static int case_unlock_mismatch(void) {
    static uint32_t word;
    word = MAIN_TAG;
    CHECK(d3_sync_unlock(&word, g_worker_tag) == RES_INVALID_STATE);
    CHECK(word == MAIN_TAG);
    CHECK(d3_sync_unlock(&word, UINT32_C(0x77)) == RES_INVALID_STATE);
    CHECK(word == MAIN_TAG);
    CHECK(d3_sync_unlock(&word, MAIN_TAG) == 0);
    CHECK(__atomic_load_n(&word, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

/* 5. ArbitrateLock handoff: a waiter on a matching word blocks until the holder
   unlocks, then owns the word under its own tag with the mask cleared. */
static int case_handoff(void) {
    static uint32_t mutex;
    mutex = MAIN_TAG | WAIT_MASK; /* held by main, contended */
    HoArg a;
    ho_arg_init(&a, MAIN_TAG, g_worker_tag, &mutex);
    pthread_t thread;
    CHECK(pthread_create(&thread, NULL, ho_waiter, &a) == 0);
    while (!__atomic_load_n(&a.entered, __ATOMIC_ACQUIRE)) {
        SPIN_BARRIER();
    }
    msleep(100); /* let it reach the wait and block */
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == (MAIN_TAG | WAIT_MASK));
    CHECK(d3_sync_unlock(&mutex, MAIN_TAG) == 0); /* hands the lock over */
    CHECK(pthread_join(thread, NULL) == 0);
    CHECK(a.lock_rc == 0);
    CHECK(a.held == g_worker_tag); /* owned under its own tag */
    CHECK(a.unlock_rc == 0);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

/* 6. Two waiters: the first handoff carries the wait-mask (another is queued),
   the second is handed the word clean. */
static int case_waitmask(void) {
    static uint32_t mutex;
    mutex = MAIN_TAG | WAIT_MASK;
    HoArg a, b;
    ho_arg_init(&a, MAIN_TAG, g_worker_tag, &mutex);
    ho_arg_init(&b, MAIN_TAG, g_worker2_tag, &mutex);
    pthread_t t1, t2;
    CHECK(pthread_create(&t1, NULL, ho_waiter, &a) == 0);
    CHECK(pthread_create(&t2, NULL, ho_waiter, &b) == 0);
    while (!__atomic_load_n(&a.entered, __ATOMIC_ACQUIRE) ||
           !__atomic_load_n(&b.entered, __ATOMIC_ACQUIRE)) {
        SPIN_BARRIER();
    }
    msleep(120);
    CHECK(d3_sync_unlock(&mutex, MAIN_TAG) == 0);
    CHECK(pthread_join(t1, NULL) == 0);
    CHECK(pthread_join(t2, NULL) == 0);
    CHECK(a.lock_rc == 0 && b.lock_rc == 0);
    CHECK(a.unlock_rc == 0 && b.unlock_rc == 0);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    uint32_t ta = a.held & ~WAIT_MASK;
    uint32_t tb = b.held & ~WAIT_MASK;
    CHECK((ta == g_worker_tag && tb == g_worker2_tag) ||
          (ta == g_worker2_tag && tb == g_worker_tag));
    CHECK(((a.held ^ b.held) & WAIT_MASK) == WAIT_MASK); /* exactly one contended */
    return 0;
}

/* 7. A zero timeout releases the mutex, returns 0xea01, and does not reacquire. */
static int case_wait_timeout0(void) {
    static uint32_t mutex, key;
    mutex = MAIN_TAG;
    key = 0;
    CHECK(d3_sync_wait(&mutex, &key, MAIN_TAG, 0) == TIMED_OUT);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    CHECK(key == 1); /* the waiter hint is left set */
    return 0;
}

/* 8. A finite wait blocks for its whole timeout (not a busy poll), then leaves
   the mutex released for the SDK to reacquire. */
static int case_wait_finite(void) {
    static uint32_t mutex, key;
    mutex = MAIN_TAG;
    key = 0;
    struct timespec start;
    clock_gettime(CLOCK_MONOTONIC, &start);
    uint32_t rc = d3_sync_wait(&mutex, &key, MAIN_TAG, INT64_C(150000000)); /* 150 ms */
    int64_t elapsed = ns_since(&start);
    CHECK(rc == TIMED_OUT);
    CHECK(elapsed >= INT64_C(100000000)); /* actually waited */
    CHECK(elapsed < INT64_C(1500000000)); /* and did return */
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    CHECK(key == 1);
    return 0;
}

/* 9. An infinite wait wakes only on its key, and only reacquires the mutex. */
static int case_wait_infinite_key(void) {
    static uint32_t mutex, key, other;
    mutex = g_worker_tag; /* wait requires the mutex word to be the waiter's tag */
    key = 0;
    other = 0;
    WaitArg a;
    wait_arg_init(&a, &mutex, &key, g_worker_tag, -1);
    pthread_t thread;
    CHECK(pthread_create(&thread, NULL, wait_thread, &a) == 0);
    /* wait until it has released the mutex and published the hint */
    while (__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 0 ||
           __atomic_load_n(&mutex, __ATOMIC_ACQUIRE) != 0) {
        SPIN_BARRIER();
    }
    msleep(50);
    CHECK(d3_sync_signal(&other, 1) == 0); /* a different key must not wake it */
    msleep(50);
    CHECK(!__atomic_load_n(&a.done, __ATOMIC_ACQUIRE));
    CHECK(a.rc == SENTINEL);
    CHECK(d3_sync_signal(&key, 1) == 0); /* the matching key does */
    CHECK(pthread_join(thread, NULL) == 0);
    CHECK(a.rc == 0);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == g_worker_tag);
    CHECK(__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 0); /* no waiter left */
    CHECK(d3_sync_unlock(&mutex, g_worker_tag) == 0);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

/* 10. signal-before-sleep: signal as soon as the hint appears, across many
   rounds. The hint is published while the waiter still holds the module lock it
   only releases asleep, so the signal cannot slip in before it queues. */
static int case_wake_race(void) {
    static uint32_t mutex, key;
    for (int round = 0; round < RACE_ROUNDS; round++) {
        mutex = MAIN_TAG;
        __atomic_store_n(&key, 0, __ATOMIC_RELEASE);
        WaitArg a;
        wait_arg_init(&a, &mutex, &key, MAIN_TAG, -1);
        pthread_t thread;
        CHECK(pthread_create(&thread, NULL, wait_thread, &a) == 0);
        while (__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 0) {
            SPIN_BARRIER();
        }
        CHECK(d3_sync_signal(&key, 1) == 0);
        CHECK(pthread_join(thread, NULL) == 0);
        CHECK(a.rc == 0);
        CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == MAIN_TAG);
    }
    return 0;
}

/* 11. A signal sent while the mutex is held elsewhere must not complete the
   wait early: the waiter queues for the mutex and finishes on its release. */
static int case_reacquire_contended(void) {
    static uint32_t mutex, key;
    mutex = g_worker_tag; /* wait requires the mutex word to be the waiter's tag */
    key = 0;
    WaitArg a;
    wait_arg_init(&a, &mutex, &key, g_worker_tag, -1);
    pthread_t thread;
    CHECK(pthread_create(&thread, NULL, wait_thread, &a) == 0);
    while (__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) != 0) {
        SPIN_BARRIER();
    }
    __atomic_store_n(&mutex, MAIN_TAG | WAIT_MASK, __ATOMIC_RELEASE); /* stolen */
    CHECK(d3_sync_signal(&key, 1) == 0);
    msleep(50);
    CHECK(!__atomic_load_n(&a.done, __ATOMIC_ACQUIRE));
    CHECK(a.rc == SENTINEL);
    CHECK(d3_sync_unlock(&mutex, MAIN_TAG) == 0); /* hand off to the waiter */
    CHECK(pthread_join(thread, NULL) == 0);
    CHECK(a.rc == 0);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == g_worker_tag);
    CHECK(d3_sync_unlock(&mutex, g_worker_tag) == 0);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

/* 12. A finite deadline still applies while the waiter is queued for the mutex:
   a signal that only re-queues it lets the deadline expire to 0xea01. */
static int case_deadline_covers_reacquire(void) {
    static uint32_t mutex, key;
    mutex = g_worker_tag; /* wait requires the mutex word to be the waiter's tag */
    key = 0;
    WaitArg a;
    wait_arg_init(&a, &mutex, &key, g_worker_tag, INT64_C(150000000)); /* 150 ms */
    struct timespec start;
    clock_gettime(CLOCK_MONOTONIC, &start);
    pthread_t thread;
    CHECK(pthread_create(&thread, NULL, wait_thread, &a) == 0);
    while (__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) != 0) {
        SPIN_BARRIER();
    }
    __atomic_store_n(&mutex, MAIN_TAG | WAIT_MASK, __ATOMIC_RELEASE); /* held elsewhere */
    CHECK(d3_sync_signal(&key, 1) == 0); /* re-queues for the mutex, no wake */
    CHECK(pthread_join(thread, NULL) == 0);
    int64_t elapsed = ns_since(&start);
    CHECK(a.rc == TIMED_OUT);
    CHECK(elapsed >= INT64_C(100000000)); /* waited out the deadline */
    CHECK(elapsed < INT64_C(1500000000));
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == (MAIN_TAG | WAIT_MASK));
    CHECK(d3_sync_unlock(&mutex, MAIN_TAG) == 0); /* no waiter left */
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

/* 13. count > 0 wakes at most that many; the rest stay, and the hint stays set. */
static int case_signal_wake_one(void) {
    static uint32_t key;
    static uint32_t mutex[3];
    WaitArg a[3];
    pthread_t thread[3];
    key = 0;
    for (int i = 0; i < 3; i++) {
        mutex[i] = MAIN_TAG;
        wait_arg_init(&a[i], &mutex[i], &key, MAIN_TAG, -1);
        CHECK(pthread_create(&thread[i], NULL, wait_thread, &a[i]) == 0);
    }
    for (int i = 0; i < 3; i++) {
        while (__atomic_load_n(&mutex[i], __ATOMIC_ACQUIRE) != 0) {
            SPIN_BARRIER();
        }
    }
    msleep(100); /* all three asleep on the key */

    CHECK(d3_sync_signal(&key, 1) == 0);
    msleep(100);
    int woken = 0;
    for (int i = 0; i < 3; i++)
        woken += __atomic_load_n(&a[i].done, __ATOMIC_ACQUIRE) ? 1 : 0;
    CHECK(woken == 1);
    CHECK(__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 1); /* two waiters remain */

    CHECK(d3_sync_signal(&key, -1) == 0); /* count <= 0: wake all */
    for (int i = 0; i < 3; i++)
        CHECK(pthread_join(thread[i], NULL) == 0);
    for (int i = 0; i < 3; i++) {
        CHECK(a[i].rc == 0);
        CHECK(__atomic_load_n(&mutex[i], __ATOMIC_ACQUIRE) == MAIN_TAG);
        CHECK(d3_sync_unlock(&mutex[i], MAIN_TAG) == 0);
    }
    CHECK(__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 0); /* cleared, none left */
    return 0;
}

/* 14. count == 0 wakes every waiter and clears the hint. */
static int case_signal_wake_all(void) {
    static uint32_t key;
    static uint32_t mutex[2];
    WaitArg a[2];
    pthread_t thread[2];
    key = 0;
    for (int i = 0; i < 2; i++) {
        mutex[i] = MAIN_TAG;
        wait_arg_init(&a[i], &mutex[i], &key, MAIN_TAG, -1);
        CHECK(pthread_create(&thread[i], NULL, wait_thread, &a[i]) == 0);
    }
    for (int i = 0; i < 2; i++) {
        while (__atomic_load_n(&mutex[i], __ATOMIC_ACQUIRE) != 0) {
            SPIN_BARRIER();
        }
    }
    msleep(100);
    CHECK(d3_sync_signal(&key, 0) == 0);
    for (int i = 0; i < 2; i++)
        CHECK(pthread_join(thread[i], NULL) == 0);
    for (int i = 0; i < 2; i++) {
        CHECK(a[i].rc == 0);
        CHECK(__atomic_load_n(&mutex[i], __ATOMIC_ACQUIRE) == MAIN_TAG);
        CHECK(d3_sync_unlock(&mutex[i], MAIN_TAG) == 0);
    }
    CHECK(__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

/* A plausible SVC frame: x0..x3 are the syscall arguments. x[29]/x[30] stay 0
   (there is no guest image), which the dispatch tolerates. */
static d3_saved svc_frame(uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3) {
    d3_saved s;
    memset(&s, 0, sizeof s);
    s.x[0] = x0;
    s.x[1] = x1;
    s.x[2] = x2;
    s.x[3] = x3;
    return s;
}

/* 15. SVC ABI: the sync syscalls reach the module through the real dispatch
   table and marshal exactly as Horizon expects. The implicit current-thread tag
   0x1B passes is D3_THREAD_ID (1) -- the single-guest context value; this does
   not imply multi-threaded guest support (CreateThread/Start are still stubs). */
static int case_svc_abi(void) {
    const uint64_t region = this_guest_tls();
    const uint64_t tlr = guest_tlr_for_tp(region);
    const uint64_t current_thread = *(uint64_t *)(uintptr_t)(tlr + 0x1f8);
    *(uint32_t *)(uintptr_t)(current_thread + 0x1b0) = MAIN_TAG;
    thread_region_set_host_tp(host_thread_pointer());
    __asm__ volatile("mov %0, x18" : "=r"(g_host_x18));
    d3_saved saved;

    /* 0x1A ArbitrateLock: a word that is not (owner | mask) returns 0 and is
       left untouched; x1/x2 survive. */
    static uint32_t word;
    word = UINT32_C(0x2468ace0);
    saved = svc_frame(MAIN_TAG, (uint64_t)(uintptr_t)&word, g_worker_tag, 0);
    d3_hle_dispatch(D3_KIND_SVC, 0x1A, &saved, region);
    CHECK(saved.x[0] == 0);
    CHECK(saved.x[1] == (uint64_t)(uintptr_t)&word);
    CHECK(saved.x[2] == g_worker_tag);
    CHECK(word == UINT32_C(0x2468ace0));
    /* 0x1A matching word the current thread already owns: returns 0. */
    word = MAIN_TAG;
    saved = svc_frame(MAIN_TAG, (uint64_t)(uintptr_t)&word, MAIN_TAG, 0);
    d3_hle_dispatch(D3_KIND_SVC, 0x1A, &saved, region);
    CHECK(saved.x[0] == 0);
    CHECK(word == MAIN_TAG);

    /* 0x1B Unlock: the implicit current-thread tag is D3_THREAD_ID. Unlocking a
       word it owns releases it; x0 becomes the result and the word clears. */
    static uint32_t mutex;
    mutex = MAIN_TAG;
    saved = svc_frame((uint64_t)(uintptr_t)&mutex, SENTINEL, SENTINEL, 0);
    d3_hle_dispatch(D3_KIND_SVC, 0x1B, &saved, region);
    CHECK(saved.x[0] == 0);
    CHECK(saved.x[1] == SENTINEL);
    CHECK(saved.x[2] == SENTINEL);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);

    /* 0x1C WaitProcessWideKeyAtomic, timeout 0: returns 0xea01, releases the
       mutex and does not reacquire it; the key hint is left set. */
    static uint32_t key;
    mutex = MAIN_TAG;
    key = 0;
    saved = svc_frame((uint64_t)(uintptr_t)&mutex, (uint64_t)(uintptr_t)&key, MAIN_TAG, 0);
    d3_hle_dispatch(D3_KIND_SVC, 0x1C, &saved, region);
    CHECK(saved.x[0] == TIMED_OUT);
    CHECK(saved.x[1] == (uint64_t)(uintptr_t)&key);
    CHECK(saved.x[2] == MAIN_TAG);
    CHECK(__atomic_load_n(&mutex, __ATOMIC_ACQUIRE) == 0);
    CHECK(key == 1);

    /* 0x1D SignalProcessWideKey: void -- x0 and x1/x2 are left as the caller
       passed them; a key with no waiter is cleared to 0. */
    key = 1;
    saved = svc_frame((uint64_t)(uintptr_t)&key, 0, SENTINEL, SENTINEL);
    d3_hle_dispatch(D3_KIND_SVC, 0x1D, &saved, region);
    CHECK(saved.x[0] == (uint64_t)(uintptr_t)&key); /* unchanged */
    CHECK(saved.x[1] == 0);
    CHECK(saved.x[2] == SENTINEL);
    CHECK(__atomic_load_n(&key, __ATOMIC_ACQUIRE) == 0);
    return 0;
}

#define RUN_CASE(fn) do { \
    int result_ = -1; \
    CHECK(run_case(fn, &result_) == 0); \
    CHECK(result_ == 0); \
} while (0)

static int case_address_cache(void) {
    uint32_t *word = mmap(NULL, PAGE_SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(word != MAP_FAILED);
    d3_sync_enable_address_cache(1);
    CHECK(d3_sync_signal(word, 1) == 0);
    const uint32_t cached = g_address_cache_next;
    CHECK(cached > 0);
    CHECK(d3_sync_signal(word, 1) == 0 && g_address_cache_next == cached);
    range_prot((uint64_t)(uintptr_t)word, PAGE_SIZE, 1, "test-cache-readonly");
    CHECK(d3_sync_signal(word, 1) == RES_INVALID_MEMORY);
    CHECK(sync_address_access(word, 0) == 0);
    range_prot((uint64_t)(uintptr_t)word, PAGE_SIZE, 0, "test-cache-unmapped");
    CHECK(sync_address_access(word, 0) == RES_INVALID_MEMORY);
    range_prot((uint64_t)(uintptr_t)word, PAGE_SIZE, 3, "test-cache-writable");
    CHECK(d3_sync_signal(word, 1) == 0);
    d3_sync_enable_address_cache(0);
    CHECK(munmap(word, PAGE_SIZE) == 0);
    return 0;
}

static void *delayed_exit(void *argument) {
    ThreadStart *start = argument;
    msleep(2200);
    pthread_mutex_lock(&start->mutex);
    start->exited = 1;
    pthread_cond_broadcast(&start->cond);
    pthread_mutex_unlock(&start->mutex);
    return NULL;
}

static int case_scene_loading_wait(void) {
    ThreadStart start = {0};
    thread_state_init(&start);
    const uint32_t handle = d3_handle_alloc(D3_OBJ_THREAD, "delayed-loader", (uint64_t)(uintptr_t)&start);
    CHECK(handle != 0);
    pthread_t worker;
    CHECK(pthread_create(&worker, NULL, delayed_exit, &start) == 0);
    int32_t index = -1;
    d3_saved saved = svc_frame((uint64_t)(uintptr_t)&index, (uint64_t)(uintptr_t)&handle, 1, UINT64_MAX);
    struct timespec begin; clock_gettime(CLOCK_MONOTONIC, &begin);
    d3_hle_dispatch(D3_KIND_SVC, 0x18, &saved, this_guest_tls());
    CHECK(saved.x[0] == 0 && saved.x[1] == 0 && index == 0);
    CHECK(ns_since(&begin) >= 2100000000LL);
    CHECK(pthread_join(worker, NULL) == 0);
    d3_handle_close(handle);
    pthread_cond_destroy(&start.cond); pthread_mutex_destroy(&start.mutex);
    return 0;
}

int main(void) {
    g_worker_tag = d3_handle_alloc(D3_OBJ_THREAD, "sync-waiter", 0);
    CHECK(g_worker_tag != 0);
    CHECK(d3_handle_kind(g_worker_tag) == D3_OBJ_THREAD);
    g_worker2_tag = d3_handle_alloc(D3_OBJ_THREAD, "sync-waiter-2", 0);
    CHECK(g_worker2_tag != 0 && g_worker2_tag != g_worker_tag);
    CHECK(d3_handle_kind(g_worker2_tag) == D3_OBJ_THREAD);

    RUN_CASE(case_alignment);
    RUN_CASE(case_invalid_memory);
    RUN_CASE(case_address_cache);
    RUN_CASE(case_invalid_owner);
    RUN_CASE(case_unlock_mismatch);
    RUN_CASE(case_handoff);
    RUN_CASE(case_waitmask);
    RUN_CASE(case_wait_timeout0);
    RUN_CASE(case_wait_finite);
    RUN_CASE(case_wait_infinite_key);
    RUN_CASE(case_wake_race);
    RUN_CASE(case_reacquire_contended);
    RUN_CASE(case_deadline_covers_reacquire);
    RUN_CASE(case_signal_wake_one);
    RUN_CASE(case_signal_wake_all);
    RUN_CASE(case_svc_abi);
    RUN_CASE(case_scene_loading_wait);

    puts("PASS: sync lock/unlock/wait/signal honour handoff, timeout and key "
         "semantics, and the 0x1A-0x1D SVC ABI");
    return 0;
}
