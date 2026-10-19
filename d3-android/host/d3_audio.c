#define _GNU_SOURCE
#include "d3_audio.h"
#include <aaudio/AAudio.h>
#include <android/log.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <sys/uio.h>
#include <unistd.h>

#define OUTPUTS 4
#define BUFFERS 64
typedef struct { uint64_t tag; int16_t *data; size_t frames, cursor; } AudioBuffer;
typedef struct {
    AAudioStream *stream;
    uint32_t channels, rate, event;
    unsigned head, count, released_head, released_count;
    uint64_t released[BUFFERS], played, nonzero, next_report;
    AudioBuffer queue[BUFFERS];
    int used, started;
    float volume;
    atomic_int disconnected;
    void (*notify)(uint32_t, int);
} AudioOut;
static AudioOut outputs[OUTPUTS];
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t lifecycle = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t recovery_once = PTHREAD_ONCE_INIT;
static atomic_int active = 1;

static void signal_event(AudioOut *out) {
    if (out->notify && out->event) out->notify(out->event, out->released_count != 0);
}

static void release_front(AudioOut *out) {
    AudioBuffer *b = &out->queue[out->head];
    out->released[(out->released_head + out->released_count++) % BUFFERS] = b->tag;
    free(b->data);
    memset(b, 0, sizeof *b);
    out->head = (out->head + 1) % BUFFERS;
    out->count--;
    signal_event(out);
}

static int16_t clip(float sample) {
    return sample > 32767 ? 32767 : sample < -32768 ? -32768 : (int16_t)sample;
}

static aaudio_data_callback_result_t render(AAudioStream *stream, void *context,
                                          void *data, int32_t frames) {
    (void)stream;
    AudioOut *out = context;
    int16_t *dst = data;
    memset(dst, 0, (size_t)frames * 2 * sizeof *dst);
    if (!atomic_load(&active) || pthread_mutex_trylock(&mutex) != 0)
        return AAUDIO_CALLBACK_RESULT_CONTINUE;
    int32_t done = 0;
    while (out->started && out->count && done < frames) {
        AudioBuffer *b = &out->queue[out->head];
        size_t count = b->frames - b->cursor;
        if (count > (size_t)(frames - done)) count = (size_t)(frames - done);
        for (size_t i = 0; i < count; i++) {
            const int16_t *src = b->data + (b->cursor + i) * out->channels;
            float l = src[0], r = out->channels == 1 ? src[0] : src[1];
            if (out->channels == 6) {
                l += .7071f * src[2] + .5f * src[3] + .7071f * src[4];
                r += .7071f * src[2] + .5f * src[3] + .7071f * src[5];
                l *= .4142f; r *= .4142f;
            }
            dst[(done + i) * 2] = clip(l * out->volume);
            dst[(done + i) * 2 + 1] = clip(r * out->volume);
            if (l != 0 || r != 0) out->nonzero++;
        }
        b->cursor += count; out->played += count; done += (int32_t)count;
        if (b->cursor == b->frames) release_front(out);
    }
    pthread_mutex_unlock(&mutex);
    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

static void stream_error(AAudioStream *stream, void *context, aaudio_result_t error) {
    (void)stream;
    AudioOut *out = context;
    atomic_store(&out->disconnected, 1);
    __android_log_print(ANDROID_LOG_ERROR, "d3audio", "stream disconnected: %s", AAudio_convertResultToText(error));
}

static int open_stream(AudioOut *out) {
    AAudioStreamBuilder *builder = NULL;
    aaudio_result_t result = AAudio_createStreamBuilder(&builder);
    if (result != AAUDIO_OK) return -1;
    AAudioStreamBuilder_setDirection(builder, AAUDIO_DIRECTION_OUTPUT);
    AAudioStreamBuilder_setSharingMode(builder, AAUDIO_SHARING_MODE_SHARED);
    AAudioStreamBuilder_setPerformanceMode(builder, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    AAudioStreamBuilder_setUsage(builder, AAUDIO_USAGE_GAME);
    AAudioStreamBuilder_setContentType(builder, AAUDIO_CONTENT_TYPE_MUSIC);
    AAudioStreamBuilder_setSampleRate(builder, (int32_t)out->rate);
    AAudioStreamBuilder_setChannelCount(builder, 2);
    AAudioStreamBuilder_setFormat(builder, AAUDIO_FORMAT_PCM_I16);
    AAudioStreamBuilder_setDataCallback(builder, render, out);
    AAudioStreamBuilder_setErrorCallback(builder, stream_error, out);
    result = AAudioStreamBuilder_openStream(builder, &out->stream);
    AAudioStreamBuilder_delete(builder);
    if (result != AAUDIO_OK) { out->stream = NULL; return -1; }
    AAudioStream_setBufferSizeInFrames(out->stream, AAudioStream_getFramesPerBurst(out->stream) * 3);
    atomic_store(&out->disconnected, 0);
    return 0;
}

static void *recover_streams(void *argument) {
    (void)argument;
    for (;;) {
        usleep(250000);
        pthread_mutex_lock(&lifecycle);
        for (unsigned i = 0; i < OUTPUTS; i++) {
            AudioOut *out = &outputs[i];
            if (!out->used || !atomic_load(&out->disconnected)) continue;
            if (out->stream) AAudioStream_close(out->stream);
            out->stream = NULL;
            if (open_stream(out) != 0) continue;
            if (out->started && AAudioStream_requestStart(out->stream) != AAUDIO_OK)
                atomic_store(&out->disconnected, 1);
            __android_log_print(ANDROID_LOG_INFO, "d3audio", "device route reopened id=%u", i);
        }
        pthread_mutex_unlock(&lifecycle);
    }
    return NULL;
}

static void start_recovery(void) {
    pthread_t worker;
    if (!pthread_create(&worker, NULL, recover_streams, NULL)) pthread_detach(worker);
}

int d3_audio_open(uint32_t rate, uint32_t channels) {
    if (!rate) rate = 48000;
    if (!channels) channels = 2;
    if (rate != 48000 || (channels != 1 && channels != 2 && channels != 6)) return -1;
    pthread_mutex_lock(&lifecycle);
    pthread_mutex_lock(&mutex);
    unsigned id;
    for (id = 0; id < OUTPUTS && outputs[id].used; id++) {}
    if (id == OUTPUTS) { pthread_mutex_unlock(&mutex); pthread_mutex_unlock(&lifecycle); return -1; }
    AudioOut *out = &outputs[id];
    memset(out, 0, sizeof *out); out->used = 1; out->channels = channels; out->rate = rate; out->volume = 1;
    pthread_mutex_unlock(&mutex);
    int result = open_stream(out);
    if (result) out->used = 0;
    pthread_mutex_unlock(&lifecycle);
    if (result) return -1;
    pthread_once(&recovery_once, start_recovery);
    __android_log_print(ANDROID_LOG_INFO, "d3audio", "open id=%u %uHz guestChannels=%u stereo PCM16", id, rate, channels);
    return (int)id;
}

void d3_audio_close(unsigned id) {
    if (id >= OUTPUTS) return;
    pthread_mutex_lock(&lifecycle);
    /* Closing waits for callbacks, so it must happen outside their mutex. */
    AAudioStream *stream = outputs[id].stream;
    if (stream) AAudioStream_close(stream);
    pthread_mutex_lock(&mutex);
    AudioOut *out = &outputs[id];
    while (out->count) release_front(out);
    memset(out, 0, sizeof *out);
    pthread_mutex_unlock(&mutex);
    pthread_mutex_unlock(&lifecycle);
}

int d3_audio_start(unsigned id, int start) {
    if (id >= OUTPUTS) return -1;
    pthread_mutex_lock(&lifecycle);
    if (!outputs[id].stream || atomic_load(&outputs[id].disconnected)) { pthread_mutex_unlock(&lifecycle); return -1; }
    AudioOut *out = &outputs[id];
    pthread_mutex_lock(&mutex); out->started = start; pthread_mutex_unlock(&mutex);
    aaudio_result_t result = start ? AAudioStream_requestStart(out->stream) : AAudioStream_requestStop(out->stream);
    if (result != AAUDIO_OK) { pthread_mutex_lock(&mutex); out->started = 0; pthread_mutex_unlock(&mutex); }
    pthread_mutex_unlock(&lifecycle);
    return result == AAUDIO_OK ? 0 : -1;
}

int d3_audio_append(unsigned id, const d3_audio_buffer *buffer, uint64_t tag) {
    if (id >= OUTPUTS || !outputs[id].used || !buffer || !tag ||
        buffer->offset > buffer->capacity || buffer->size > buffer->capacity - buffer->offset ||
        buffer->size > 4 * 1024 * 1024 || !buffer->size ||
        buffer->samples > UINT64_MAX - buffer->offset) return -1;
    AudioOut *out = &outputs[id];
    if (buffer->size % (out->channels * 2)) return -1;
    int16_t *copy = malloc((size_t)buffer->size);
    if (!copy) return -1;
    struct iovec local = {copy, (size_t)buffer->size};
    struct iovec remote = {(void *)(uintptr_t)(buffer->samples + buffer->offset), (size_t)buffer->size};
    if (process_vm_readv(getpid(), &local, 1, &remote, 1, 0) != (ssize_t)buffer->size) { free(copy); return -1; }
    pthread_mutex_lock(&mutex);
    if (out->count + out->released_count >= BUFFERS) { pthread_mutex_unlock(&mutex); free(copy); return -1; }
    AudioBuffer *b = &out->queue[(out->head + out->count++) % BUFFERS];
    *b = (AudioBuffer){tag, copy, (size_t)buffer->size / (out->channels * 2), 0};
    pthread_mutex_unlock(&mutex);
    return 0;
}

size_t d3_audio_release(unsigned id, uint64_t *tags, size_t count) {
    if (id >= OUTPUTS) return 0;
    pthread_mutex_lock(&mutex);
    AudioOut *out = &outputs[id];
    if (count > out->released_count) count = out->released_count;
    for (size_t i = 0; i < count; i++) tags[i] = out->released[(out->released_head + i) % BUFFERS];
    out->released_head = (out->released_head + (unsigned)count) % BUFFERS;
    out->released_count -= (unsigned)count;
    signal_event(out);
    if (out->played >= out->next_report && out->played) {
        out->next_report = out->played + 480000;
        __android_log_print(ANDROID_LOG_INFO, "d3audio", "play id=%u frames=%llu nonzero=%llu queued=%u xruns=%d",
                id, (unsigned long long)out->played, (unsigned long long)out->nonzero, out->count,
                out->stream ? AAudioStream_getXRunCount(out->stream) : 0);
    }
    pthread_mutex_unlock(&mutex);
    return count;
}

void d3_audio_event(unsigned id, uint32_t event, void (*notify)(uint32_t, int)) {
    if (id >= OUTPUTS) return;
    pthread_mutex_lock(&mutex);
    outputs[id].event = event; outputs[id].notify = notify; signal_event(&outputs[id]);
    pthread_mutex_unlock(&mutex);
}
uint32_t d3_audio_state(unsigned id) {
    pthread_mutex_lock(&mutex); uint32_t value = id < OUTPUTS && outputs[id].started ? 0 : 1; pthread_mutex_unlock(&mutex); return value;
}
uint32_t d3_audio_count(unsigned id) {
    pthread_mutex_lock(&mutex); uint32_t value = id < OUTPUTS ? outputs[id].count : 0; pthread_mutex_unlock(&mutex); return value;
}
uint64_t d3_audio_played(unsigned id) {
    pthread_mutex_lock(&mutex); uint64_t value = id < OUTPUTS ? outputs[id].played : 0; pthread_mutex_unlock(&mutex); return value;
}
int d3_audio_contains(unsigned id, uint64_t tag) {
    pthread_mutex_lock(&mutex); int found = 0;
    if (id < OUTPUTS) for (unsigned i = 0; i < outputs[id].count; i++)
        if (outputs[id].queue[(outputs[id].head + i) % BUFFERS].tag == tag) found = 1;
    pthread_mutex_unlock(&mutex); return found;
}
int d3_audio_flush(unsigned id) {
    if (id >= OUTPUTS) return 0;
    pthread_mutex_lock(&mutex);
    AudioOut *out = &outputs[id];
    int flushed = out->count != 0;
    while (out->count) release_front(out);
    pthread_mutex_unlock(&mutex); return flushed;
}
float d3_audio_volume(unsigned id, float value, int set) {
    if (id >= OUTPUTS) return 0;
    pthread_mutex_lock(&mutex);
    if (set && isfinite(value)) outputs[id].volume = value < 0 ? 0 : value > 1 ? 1 : value;
    value = outputs[id].volume;
    pthread_mutex_unlock(&mutex); return value;
}
void d3_audio_active(int value) { atomic_store(&active, value != 0); }
