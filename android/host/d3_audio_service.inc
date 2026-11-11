/* AudioOut HIPC adapters. Included after the bounded guest buffer helpers. */
extern void d3_event_set(uint32_t handle, int signaled);
static void audio_reply(Message *m, uint64_t value, unsigned words) {
    reply_prepare(m, 0, words, m->domain);
    m->w[m->payload + 4] = (uint32_t)value;
    if (words > 1) m->w[m->payload + 5] = (uint32_t)(value >> 32);
    reply_send(m);
}

static void audout_command(Message *m, uint32_t command, uint32_t session) {
    uint64_t address;
    size_t size;
    static const char name[0x100] = "DeviceOut";
    if (command == 0 || command == 2) {
        if (message_io_buffer(m, 1, 0, &address, &size) && size >= sizeof name &&
            guest_write(address, name, sizeof name)) audio_reply(m, 1, 1);
        else audio_reply(m, 0, 1);
        return;
    }
    if (command != 1 && command != 3) { unsupported_command(m, D3_IF_AUDOUT, command); return; }
    uint32_t rate = m->w[m->magic + 4];
    uint32_t channels = m->w[m->magic + 5] & 0xffffu;
    if (!rate) rate = 48000;
    if (!channels) channels = 2;
    int id = d3_audio_open(rate, channels);
    if (id < 0) { reply_service_result(m, D3_RESULT(153, 1)); return; }
    if (!message_io_buffer(m, 1, 0, &address, &size) || size < sizeof name ||
        !guest_write(address, name, sizeof name)) {
        d3_audio_close((unsigned)id); reply_service_result(m, D3_RESULT(153, 2)); return;
    }
    const int domain = m->domain;
    uint32_t child;
    if (domain) {
        child = domain_add(session, D3_IF_AUDIO_OUT);
        if (child) g_domain[child - 1].arg = (uint64_t)id;
        reply_prepare(m, 0, 5, 1);
        m->w[m->frame] = 1;
        m->w[m->payload + 8] = child;
    } else {
        char child_name[24];
        snprintf(child_name, sizeof child_name, "audio-out-%d", id);
        child = d3_handle_alloc(D3_OBJ_SESSION, child_name, PORT_AUDIO_OUT);
        reply_prepare_handle(m, 1, 4, 0, REPLY_MOVE_HANDLE);
        m->w[m->handle_slot_out] = child;
    }
    if (!child) { d3_audio_close((unsigned)id); reply_service_result(m, D3_RESULT(153, 3)); return; }
    m->w[m->payload + 4] = rate;
    m->w[m->payload + 5] = channels;
    m->w[m->payload + 6] = 2; /* PcmInt16 */
    m->w[m->payload + 7] = 1; /* Stopped */
    slog("audio: open child=%#x id=%d %uHz channels=%u", child, id, rate, channels);
    reply_send(m);
}

static void audin_command(Message *m, uint32_t command) {
    /* This APK has no recording permission or microphone capture backend. */
    if (command == 0 || command == 2 || command == 4) audio_reply(m, 0, 1);
    else reply_service_result(m, D3_RESULT(153, 2));
}

static void audio_out_command(Message *m, uint32_t command, uint32_t session) {
    unsigned id = 0;
    if (m->domain) id = (unsigned)g_domain[m->domain_object - 1].arg;
    else if (sscanf(d3_handle_name(session), "audio-out-%u", &id) != 1) {
        reply_service_result(m, D3_RESULT(153, 4)); return;
    }
    uint64_t address = 0, arg = 0;
    size_t size = 0;
    memcpy(&arg, &m->w[m->magic + 4], sizeof arg);
    switch (command) {
    case 0: audio_reply(m, d3_audio_state(id), 1); return;
    case 1: case 2:
        reply_service_result(m, d3_audio_start(id, command == 1) ? D3_RESULT(153, 5) : 0); return;
    case 3: case 7: {
        d3_audio_buffer buffer;
        if (!message_io_buffer(m, 0, 0, &address, &size) || size < sizeof buffer ||
            !guest_read(&buffer, address, sizeof buffer) || d3_audio_append(id, &buffer, arg)) {
            reply_service_result(m, D3_RESULT(153, 6)); return;
        }
        reply_service_result(m, 0); return;
    }
    case 4: {
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "audio-release", 0);
        if (!event) { reply_service_result(m, D3_RESULT(153, 7)); return; }
        d3_audio_event(id, event, d3_event_set);
        reply_prepare_handle(m, 1, 0, m->domain, REPLY_COPY_HANDLE);
        m->w[m->handle_slot_out] = event; reply_send(m); return;
    }
    case 5: case 8: {
        uint64_t tags[64] = {0};
        if (!message_io_buffer(m, 1, 0, &address, &size) || size < sizeof(uint64_t)) {
            reply_service_result(m, D3_RESULT(153, 8)); return;
        }
        size_t count = size / sizeof(uint64_t);
        if (count > 64) count = 64;
        count = d3_audio_release(id, tags, count);
        if (!guest_write(address, tags, (count ? count : 1) * sizeof(uint64_t))) {
            reply_service_result(m, D3_RESULT(153, 9)); return;
        }
        audio_reply(m, count, 1); return;
    }
    case 6: audio_reply(m, d3_audio_contains(id, arg), 1); return;
    case 9: audio_reply(m, d3_audio_count(id), 1); return;
    case 10: audio_reply(m, d3_audio_played(id), 2); return;
    case 11: audio_reply(m, d3_audio_flush(id), 1); return;
    case 12: {
        float value; memcpy(&value, &m->w[m->magic + 4], 4);
        d3_audio_volume(id, value, 1); reply_service_result(m, 0); return;
    }
    case 13: {
        float value = d3_audio_volume(id, 0, 0); uint32_t bits;
        memcpy(&bits, &value, 4); audio_reply(m, bits, 1); return;
    }
    default: unsupported_command(m, D3_IF_AUDIO_OUT, command); return;
    }
}
