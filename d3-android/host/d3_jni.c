#include <jni.h>
#include <signal.h>
#include <pthread.h>
#include <time.h>
#include <stdlib.h>
#include <string.h>
#include <ucontext.h>
#include <unistd.h>
#include <android/log.h>
#include <android/native_window_jni.h>

#include "d3_host.h"
#include "d3_service.h"
#include "d3_audio.h"

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeAudioActive(JNIEnv *env, jobject activity, jboolean active) {
    (void)env;
    (void)activity;
    d3_audio_active(active);
}

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeInput(JNIEnv *env, jobject activity,
        jlong buttons, jint lx, jint ly, jint rx, jint ry) {
    (void)env;
    (void)activity;
    d3_hid_update((uint64_t)buttons, lx, ly, rx, ry);
}

static pthread_mutex_t g_surface_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_surface_ready = PTHREAD_COND_INITIALIZER;
static int g_surface_status;

static JavaVM *g_java_vm;
static jobject g_activity;
static pthread_mutex_t g_keyboard_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_keyboard_ready = PTHREAD_COND_INITIALIZER;
static uint16_t g_keyboard_text[1001];
static int g_keyboard_done, g_keyboard_result;

JNIEXPORT jstring JNICALL
Java_com_d3mobile_host_MainActivity_nativePrivateRoot(JNIEnv *env, jobject activity) {
    (void)activity;
    return (*env)->NewStringUTF(env, D3_PRIVATE_ROOT);
}

JNIEXPORT jint JNICALL
Java_com_d3mobile_host_MainActivity_nativeConfigure(JNIEnv *env, jobject activity,
        jint scale, jstring libraries, jstring directory, jstring name) {
    (void)activity;
#ifdef D3_WITH_GPU
    extern int d3_gpu_configure(int, const char*, const char*, const char*);
    const char *libs = (*env)->GetStringUTFChars(env, libraries, NULL);
    const char *dir = (*env)->GetStringUTFChars(env, directory, NULL);
    const char *file = (*env)->GetStringUTFChars(env, name, NULL);
    int result = d3_gpu_configure(scale, libs, dir, file);
    (*env)->ReleaseStringUTFChars(env, libraries, libs);
    (*env)->ReleaseStringUTFChars(env, directory, dir);
    (*env)->ReleaseStringUTFChars(env, name, file);
    return result;
#else
    (void)env; (void)scale; (void)libraries; (void)directory; (void)name;
    return -1;
#endif
}

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeAttach(JNIEnv *env, jobject activity) {
    (*env)->GetJavaVM(env, &g_java_vm);
    if (g_activity) (*env)->DeleteGlobalRef(env, g_activity);
    g_activity = (*env)->NewGlobalRef(env, activity);
}

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeKeyboardReply(JNIEnv *env, jobject activity, jstring text) {
    (void)activity;
    pthread_mutex_lock(&g_keyboard_mutex);
    memset(g_keyboard_text, 0, sizeof g_keyboard_text);
    g_keyboard_result = text ? 0 : 1;
    if (text) {
        jsize length = (*env)->GetStringLength(env, text);
        if (length > 1000) length = 1000;
        (*env)->GetStringRegion(env, text, 0, length, (jchar *)g_keyboard_text);
    }
    g_keyboard_done = 1;
    pthread_cond_signal(&g_keyboard_ready);
    pthread_mutex_unlock(&g_keyboard_mutex);
}

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeDetach(JNIEnv *env, jobject activity) {
    Java_com_d3mobile_host_MainActivity_nativeKeyboardReply(env, activity, NULL);
    pthread_mutex_lock(&g_keyboard_mutex);
    if (g_activity && (*env)->IsSameObject(env, activity, g_activity)) {
        (*env)->DeleteGlobalRef(env, g_activity);
        g_activity = NULL;
    }
    pthread_mutex_unlock(&g_keyboard_mutex);
}

int d3_keyboard_show(const uint16_t *title, const uint16_t *hint, const uint16_t *initial,
                     unsigned minimum, unsigned maximum, uint16_t *result, size_t capacity) {
    if (!g_java_vm || !g_activity) return 1;
    JNIEnv *env = NULL;
    int attached = (*g_java_vm)->GetEnv(g_java_vm, (void **)&env, JNI_VERSION_1_6) != JNI_OK;
    if (attached && (*g_java_vm)->AttachCurrentThread(g_java_vm, &env, NULL) != JNI_OK) return 1;
    pthread_mutex_lock(&g_keyboard_mutex);
    g_keyboard_done = 0;
    g_keyboard_result = 1;
    jclass cls = (*env)->GetObjectClass(env, g_activity);
    jmethodID method = (*env)->GetMethodID(env, cls, "showKeyboard", "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II)V");
    const uint16_t *texts[3] = {title, hint, initial};
    jstring strings[3];
    for (int i = 0; i < 3; i++) {
        jsize length = 0; while (texts[i][length] && length < 1000) length++;
        strings[i] = (*env)->NewString(env, (const jchar *)texts[i], length);
    }
    if (method) (*env)->CallVoidMethod(env, g_activity, method, strings[0], strings[1], strings[2], (jint)minimum, (jint)maximum);
    else g_keyboard_done = 1;
    if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionDescribe(env); (*env)->ExceptionClear(env); g_keyboard_done = 1; }
    for (int i = 0; i < 3; i++) (*env)->DeleteLocalRef(env, strings[i]);
    (*env)->DeleteLocalRef(env, cls);
    while (!g_keyboard_done) pthread_cond_wait(&g_keyboard_ready, &g_keyboard_mutex);
    if (capacity > 1001) capacity = 1001;
    memcpy(result, g_keyboard_text, capacity * sizeof(uint16_t));
    const int status = g_keyboard_result;
    pthread_mutex_unlock(&g_keyboard_mutex);
    if (attached) (*g_java_vm)->DetachCurrentThread(g_java_vm);
    return status;
}

/* Provided by the Eden GPU port (gpu/host/gpu_host.cpp / vk_clear.cpp).  The
 * plain C-only build keeps these weak so it links without the archive;
 * --with-gpu passes -DD3_WITH_GPU to make them strong references (a weak
 * undefined symbol would not pull an archive member out of libeden_gpu.a). */
#ifdef D3_WITH_GPU
extern void d3_gpu_probe_init(void);
extern int d3_vk_clear(void *native_window);
extern int d3_gpu_renderer_init(void *native_window);
extern int d3_gpu_channel_test(void);
extern int d3_gpu_bridge_start(void *native_window);
extern int d3_gpu_bridge_channel_id(void);
extern int d3_gpu_bridge_memtest(void);
extern int d3_gpu_bridge_composite_test(void);
extern void d3_gpu_set_cache_scan(int enabled);
extern void d3_gpu_set_write_watch(int enabled);
#define D3_GPU_CALL(fn, ...) fn(__VA_ARGS__)
#define D3_GPU_CHANNEL_ID() d3_gpu_bridge_channel_id()
#else
extern void d3_gpu_probe_init(void) __attribute__((weak));
extern int d3_vk_clear(void *native_window) __attribute__((weak));
extern int d3_gpu_renderer_init(void *native_window) __attribute__((weak));
extern int d3_gpu_channel_test(void) __attribute__((weak));
extern int d3_gpu_bridge_start(void *native_window) __attribute__((weak));
extern int d3_gpu_bridge_channel_id(void) __attribute__((weak));
extern int d3_gpu_bridge_memtest(void) __attribute__((weak));
extern int d3_gpu_bridge_composite_test(void) __attribute__((weak));
#define D3_GPU_CHANNEL_ID() (-1)
#define D3_GPU_CALL(fn, ...)                                                   \
    do {                                                                       \
        if (fn != NULL) {                                                      \
            fn(__VA_ARGS__);                                                   \
        }                                                                      \
    } while (0)
#endif

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativePresent(JNIEnv *env, jobject activity,
                                                   jobject surface) {
    (void)activity;
    if (!surface) {
        D3_GPU_CALL(d3_gpu_renderer_init, NULL);
        return;
    }
    ANativeWindow *window = ANativeWindow_fromSurface(env, surface);
    if (window == NULL) {
        return;
    }
    const int self_test = access(D3_DATA_ROOT "/gpu-self-test", R_OK) == 0;
    if (self_test)
        D3_GPU_CALL(d3_vk_clear, window);
    int status = 0;
#ifdef D3_WITH_GPU
    d3_gpu_set_cache_scan(access(D3_DATA_ROOT "/gpu-no-cache-scan", R_OK) != 0);
    d3_gpu_set_write_watch(access(D3_DATA_ROOT "/gpu-write-watch", R_OK) == 0);
    status = d3_gpu_bridge_start(window);
#else
    D3_GPU_CALL(d3_gpu_bridge_start, window);
#endif
    pthread_mutex_lock(&g_surface_mutex);
    g_surface_status = status == 0 ? 1 : -1;
    pthread_cond_broadcast(&g_surface_ready);
    pthread_mutex_unlock(&g_surface_mutex);
    __android_log_print(ANDROID_LOG_INFO, "d3host", "gpu bridge ready, channel=%d", D3_GPU_CHANNEL_ID());
    if (self_test) {
        D3_GPU_CALL(d3_gpu_bridge_memtest);
        D3_GPU_CALL(d3_gpu_bridge_composite_test);
    }
    ANativeWindow_release(window);
}

/* Diagnostic fault logger: the guest crash currently leaves no tombstone we can
 * read (non-root /data/tombstones), so print pc/lr/fault and then restore the
 * default action to keep crash semantics unchanged. */
static void d3_fault_logger(int sig, siginfo_t *info, void *ctx) {
    ucontext_t *uc = (ucontext_t *)ctx;
    unsigned long pc = 0, lr = 0, sp = 0;
#if defined(__aarch64__)
    pc = (unsigned long)uc->uc_mcontext.pc;
    lr = (unsigned long)uc->uc_mcontext.regs[30];
    sp = (unsigned long)uc->uc_mcontext.sp;
#endif
    __android_log_print(ANDROID_LOG_INFO, "d3fault", "sig=%d pc=%#lx lr=%#lx sp=%#lx fault=%p",
                        sig, pc, lr, sp, info ? info->si_addr : 0);
    signal(sig, SIG_DFL);
    raise(sig);
}

static void d3_install_fault_logger(void) {
    static int installed = 0;
    /* Opt-in: replacing ART's handlers changes how Java faults behave. */
    if (installed || getenv("D3_FAULT_LOG") == NULL) {
        return;
    }
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = d3_fault_logger;
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, NULL);
    sigaction(SIGBUS, &sa, NULL);
    sigaction(SIGILL, &sa, NULL);
    sigaction(SIGABRT, &sa, NULL);
    installed = 1;
}

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeStart(JNIEnv *env, jobject activity,
                                                 jstring guest_path) {
    (void)activity;

#ifdef D3_WITH_GPU
    struct timespec deadline;
    clock_gettime(CLOCK_REALTIME, &deadline);
    deadline.tv_sec += 30;
    pthread_mutex_lock(&g_surface_mutex);
    while (g_surface_status == 0) {
        if (pthread_cond_timedwait(&g_surface_ready, &g_surface_mutex, &deadline) != 0)
            break;
    }
    const int ready = g_surface_status == 1;
    pthread_mutex_unlock(&g_surface_mutex);
    if (!ready) {
        __android_log_print(ANDROID_LOG_ERROR, "d3host", "GPU surface initialization failed or timed out");
        return;
    }
    d3_gpu_probe_init();
#else
    if (d3_gpu_probe_init != NULL) {
        d3_gpu_probe_init();
    }
#endif

    const char *path = NULL;
    if (guest_path != NULL) {
        path = (*env)->GetStringUTFChars(env, guest_path, NULL);
        if (path == NULL) {
            return;
        }
    }

    d3_install_fault_logger();
    (void)d3_host_start(path);

    if (guest_path != NULL) {
        (*env)->ReleaseStringUTFChars(env, guest_path, path);
    }
}
