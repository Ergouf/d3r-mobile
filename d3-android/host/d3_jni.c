#include <jni.h>
#include <signal.h>
#include <string.h>
#include <ucontext.h>
#include <unistd.h>
#include <android/log.h>
#include <android/native_window_jni.h>

#include "d3_host.h"

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
    ANativeWindow *window = ANativeWindow_fromSurface(env, surface);
    if (window == NULL) {
        return;
    }
    /* M1 fallback: present a solid colour so the surface is never black while
     * Eden's composite path is still being brought up. */
    D3_GPU_CALL(d3_vk_clear, window);
    /* Eden's renderer + address space + channel. */
    D3_GPU_CALL(d3_gpu_renderer_init, window);
    D3_GPU_CALL(d3_gpu_bridge_start, window);
    __android_log_print(ANDROID_LOG_INFO, "d3host", "gpu bridge ready, channel=%d", D3_GPU_CHANNEL_ID());
    D3_GPU_CALL(d3_gpu_bridge_memtest);
    D3_GPU_CALL(d3_gpu_bridge_composite_test);
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
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
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
