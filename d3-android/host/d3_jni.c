#include <jni.h>

#include "d3_host.h"

/* Provided by the Eden GPU port (gpu/host/gpu_host.cpp).  The plain C-only
 * build keeps this weak so it links without the archive; --with-gpu passes
 * -DD3_WITH_GPU to make it a strong reference (a weak one would not pull the
 * archive member out of libeden_gpu.a). */
#ifdef D3_WITH_GPU
extern void d3_gpu_probe_init(void);
#else
extern void d3_gpu_probe_init(void) __attribute__((weak));
#endif

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
