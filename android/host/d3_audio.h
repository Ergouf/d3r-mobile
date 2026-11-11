#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint64_t next, samples, capacity, size, offset;
} d3_audio_buffer;

int d3_audio_open(uint32_t rate, uint32_t channels);
void d3_audio_close(unsigned id);
int d3_audio_start(unsigned id, int start);
int d3_audio_append(unsigned id, const d3_audio_buffer *buffer, uint64_t tag);
size_t d3_audio_release(unsigned id, uint64_t *tags, size_t count);
void d3_audio_event(unsigned id, uint32_t event, void (*notify)(uint32_t, int));
uint32_t d3_audio_state(unsigned id);
uint32_t d3_audio_count(unsigned id);
uint64_t d3_audio_played(unsigned id);
int d3_audio_contains(unsigned id, uint64_t tag);
int d3_audio_flush(unsigned id);
float d3_audio_volume(unsigned id, float value, int set);
void d3_audio_active(int active);
