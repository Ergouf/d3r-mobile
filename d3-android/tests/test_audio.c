#include "../host/d3_audio.c"
#include <stdio.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %d: %s\n", __LINE__, #c); return 1; } } while (0)
static int event_state;
static void notify(uint32_t event, int signaled) { if (event == 77) event_state = signaled; }

int main(void) {
    CHECK(d3_audio_open(44100, 2) < 0);
    CHECK(d3_audio_open(48000, 3) < 0);
    AudioOut *out = &outputs[0];
    out->used = 1; out->channels = 2; out->rate = 48000; out->volume = 1; out->started = 1;
    int16_t pcm[8] = {1000, -1000, 2000, -2000, 3000, -3000, 4000, -4000};
    d3_audio_buffer buffer = {0, (uint64_t)(uintptr_t)pcm, sizeof pcm, sizeof pcm, 0};
    d3_audio_event(0, 77, notify);
    CHECK(d3_audio_append(0, &buffer, 123) == 0);
    pcm[0] = 1; /* Queued samples own a snapshot; the guest may reuse its buffer. */
    CHECK(d3_audio_count(0) == 1 && d3_audio_contains(0, 123));
    int16_t output[8];
    render(NULL, out, output, 2);
    CHECK(output[0] == 1000 && output[1] == -1000 && output[2] == 2000);
    CHECK(d3_audio_played(0) == 2 && d3_audio_count(0) == 1 && !event_state);
    uint64_t tags[4] = {0};
    CHECK(d3_audio_release(0, tags, 4) == 0);
    d3_audio_active(0);
    render(NULL, out, output, 2);
    CHECK(output[0] == 0 && output[3] == 0 && d3_audio_played(0) == 2);
    d3_audio_active(1);
    render(NULL, out, output, 4);
    CHECK(output[0] == 3000 && output[2] == 4000 && output[4] == 0);
    CHECK(d3_audio_count(0) == 0 && event_state);
    CHECK(d3_audio_release(0, tags, 4) == 1 && tags[0] == 123 && !event_state);
    CHECK(!d3_audio_contains(0, 123));
    CHECK(d3_audio_append(0, &buffer, 10) == 0);
    CHECK(d3_audio_append(0, &buffer, 11) == 0);
    CHECK(d3_audio_flush(0));
    CHECK(d3_audio_release(0, tags, 1) == 1 && tags[0] == 10 && event_state);
    CHECK(d3_audio_release(0, tags, 4) == 1 && tags[0] == 11 && !event_state);
    buffer.offset = sizeof pcm;
    CHECK(d3_audio_append(0, &buffer, 12) < 0);
    buffer.offset = 0; buffer.samples = 1;
    CHECK(d3_audio_append(0, &buffer, 13) < 0);
    buffer.samples = (uint64_t)(uintptr_t)pcm;
    for (unsigned i = 0; i < 64; i++) CHECK(d3_audio_append(0, &buffer, i + 1) == 0);
    CHECK(d3_audio_append(0, &buffer, 65) < 0);
    CHECK(d3_audio_flush(0));
    uint64_t all[64];
    CHECK(d3_audio_release(0, all, 64) == 64);
    for (unsigned i = 0; i < 64; i++) CHECK(all[i] == i + 1);
    out->channels = 6;
    int16_t surround[6] = {1000, 2000, 1000, 200, 1000, 2000};
    buffer.samples = (uint64_t)(uintptr_t)surround;
    buffer.size = buffer.capacity = sizeof surround;
    CHECK(d3_audio_append(0, &buffer, 999) == 0);
    render(NULL, out, output, 1);
    CHECK(output[0] > 1000 && output[1] > output[0] && output[1] < 32767);
    CHECK(d3_audio_release(0, tags, 4) == 1 && tags[0] == 999);
    d3_audio_close(0);
    puts("PASS: real PCM mixer, partial consumption, FIFO tags/events, pause/resume, six-channel downmix, capacity and invalid guest memory");
    return 0;
}
