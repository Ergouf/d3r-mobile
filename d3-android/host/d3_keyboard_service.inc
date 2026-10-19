extern int d3_keyboard_show(const uint16_t *, const uint16_t *, const uint16_t *,
                            unsigned, unsigned, uint16_t *, size_t) __attribute__((weak));

static uint32_t keyboard_u32(const uint8_t *config, size_t offset) {
    uint32_t value; memcpy(&value, config + offset, sizeof value); return value;
}

static int keyboard_start(DomainObject *object) {
    HostStorage *config = object->input_count > 1 ? storage_of(object->inputs[1]) : NULL;
    HostStorage *work = object->input_count > 2 ? storage_of(object->inputs[2]) : NULL;
    if (!config || config->size < 0x3d4 || !d3_keyboard_show) return -1;
    uint16_t title[66] = {0}, hint[257] = {0}, initial[1001] = {0}, text[1001] = {0};
    memcpy(title, config->data + 0x24, 130);
    memcpy(hint, config->data + 0x1a8, 512);
    unsigned maximum = keyboard_u32(config->data, 0x3ac);
    unsigned minimum = keyboard_u32(config->data, 0x3b0);
    if (!maximum || maximum > 1000) maximum = 1000;
    if (minimum > maximum) minimum = 0;
    uint32_t offset = keyboard_u32(config->data, 0x3c0);
    uint32_t length = keyboard_u32(config->data, 0x3c4);
    if (work && length <= 1000 && offset <= work->size && length * 2 <= work->size - offset)
        memcpy(initial, work->data + offset, length * 2);
    const int cancelled = d3_keyboard_show(title, hint, initial, minimum, maximum, text, 1001);
    uint32_t output = storage_create(0x7d8);
    HostStorage *storage = storage_of(output);
    if (!storage) return -1;
    uint32_t result = cancelled ? 1 : 0;
    memcpy(storage->data, &result, 4);
    if (config->data[0x3bd]) {
        size_t cursor = 4;
        for (size_t i = 0; i < 1000 && text[i]; i++) {
            uint32_t code = text[i];
            if (code >= 0xd800 && code <= 0xdbff && text[i + 1] >= 0xdc00 && text[i + 1] <= 0xdfff)
                code = 0x10000 + ((code - 0xd800) << 10) + text[++i] - 0xdc00;
            unsigned bytes = code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
            if (cursor + bytes >= storage->size) break;
            if (bytes == 1) storage->data[cursor++] = (uint8_t)code;
            else {
                storage->data[cursor++] = (uint8_t)((bytes == 2 ? 0xc0 : bytes == 3 ? 0xe0 : 0xf0) | (code >> (6 * (bytes - 1))));
                for (unsigned n = bytes - 1; n; n--) storage->data[cursor++] = (uint8_t)(0x80 | ((code >> (6 * (n - 1))) & 63));
            }
        }
    } else memcpy(storage->data + 4, text, sizeof text - 2);
    object->output_storage = output;
    object->initialized = 1;
    if (!cancelled && config->data[0x3d0]) {
        object->initialized = 0;
        object->interactive_storage = storage_create(0x7dc);
        HostStorage *interactive = storage_of(object->interactive_storage);
        if (!interactive) return -1;
        size_t bytes = 0;
        if (config->data[0x3bd]) {
            while (bytes < 0x7d3 && storage->data[4 + bytes]) bytes++;
            bytes++;
        } else {
            while (bytes < 2000 && text[bytes / 2]) bytes += 2;
            bytes += 2;
        }
        uint64_t length_bytes = bytes;
        memcpy(interactive->data, &length_bytes, 8);
        memcpy(interactive->data + 8, storage->data + 4, bytes);
    }
    slog("keyboard submitted cancelled=%d check=%u completed=%d interactive=%u", cancelled,
        config->data[0x3d0], object->initialized, object->interactive_storage);
    return 0;
}
