#include <jni.h>

#include "d3_host.h"

JNIEXPORT void JNICALL
Java_com_d3mobile_host_MainActivity_nativeStart(JNIEnv *env, jobject activity,
                                                 jstring guest_path) {
    (void)activity;

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
