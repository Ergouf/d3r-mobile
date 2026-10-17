#include <jni.h>
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
#define D3_GPU_CALL(fn, ...) fn(__VA_ARGS__)
#define D3_GPU_CHANNEL_ID() d3_gpu_bridge_channel_id()
#else
extern void d3_gpu_probe_init(void) __attribute__((weak));
extern int d3_vk_clear(void *native_window) __attribute__((weak));
extern int d3_gpu_renderer_init(void *native_window) __attribute__((weak));
extern int d3_gpu_channel_test(void) __attribute__((weak));
extern int d3_gpu_bridge_start(void *native_window) __attribute__((weak));
extern int d3_gpu_bridge_channel_id(void) __attribute__((weak));
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
    D3_GPU_CALL(d3_vk_clear, window);
    /* Bring Eden's real renderer up on the same surface; the clear above stays
     * as the visual fallback until composites are driven by the guest. */
    D3_GPU_CALL(d3_gpu_renderer_init, window);
    D3_GPU_CALL(d3_gpu_bridge_start, window);
    __android_log_print(ANDROID_LOG_INFO, "d3host", "gpu bridge ready, channel=%d", D3_GPU_CHANNEL_ID());
    ANativeWindow_release(window);
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

    (void)d3_host_start(path);

    if (guest_path != NULL) {
        (*env)->ReleaseStringUTFChars(env, guest_path, path);
    }
}
