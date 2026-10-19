#include "../host/d3_service.c"
#include <assert.h>

void d3_trace_guest(const char *tag, const d3_saved *saved) { (void)tag; (void)saved; }
static int cancel_input;
int d3_keyboard_show(const uint16_t *title, const uint16_t *hint, const uint16_t *initial,
                     unsigned minimum, unsigned maximum, uint16_t *out, size_t capacity) {
    (void)title; (void)hint; (void)initial;
    assert(minimum == 1 && maximum == 12 && capacity >= 4);
    out[0] = 'A'; out[1] = 0xd83d; out[2] = 0xde00; out[3] = 0;
    return cancel_input;
}

int main(void) {
    const uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", 0);
    const uint32_t id = domain_add(session, D3_IF_LIBRARY_APPLET_ACCESSOR);
    DomainObject *object = &g_domain[id - 1];
    object->arg = 0x11;
    object->inputs[0] = storage_create(32);
    object->inputs[1] = storage_create(0x4c8);
    object->input_count = 2;
    HostStorage *config = storage_of(object->inputs[1]);
    uint32_t min = 1, max = 12;
    memcpy(config->data + 0x3ac, &max, 4); memcpy(config->data + 0x3b0, &min, 4);
    assert(keyboard_start(object) == 0 && object->initialized);
    HostStorage *out = storage_of(object->output_storage);
    assert(out && out->size == 0x7d8 && keyboard_u32(out->data, 0) == 0);
    assert(out->data[4] == 'A' && out->data[6] == 0x3d && out->data[7] == 0xd8);
    assert(!object->interactive_storage);
    uint32_t words[MESSAGE_WORDS] = {0};
    Message message = {.address = (uint64_t)(uintptr_t)words, .domain = 1,
                       .domain_object = id, .frame = 4, .magic = 8, .payload = 8};
    library_applet_accessor_command(&message, 0, session);
    assert(d3_handle_arg(object->event) == 1); /* SDK can probe after a multiwait. */
    config->data[0x3bd] = 1; config->data[0x3d0] = 1;
    assert(keyboard_start(object) == 0 && !object->initialized && object->interactive_storage);
    HostStorage *interactive = storage_of(object->interactive_storage);
    const uint8_t utf8[] = {'A', 0xf0, 0x9f, 0x98, 0x80, 0};
    assert(keyboard_u32(interactive->data, 0) == sizeof utf8);
    assert(memcmp(interactive->data + 8, utf8, sizeof utf8) == 0);
    const uint32_t check_id = storage_object(session, D3_IF_STORAGE, 0x7d8);
    message.w[12] = check_id;
    library_applet_accessor_command(&message, 103, session);
    assert(object->initialized && !object->interactive_storage);
    cancel_input = 1;
    assert(keyboard_start(object) == 0 && object->initialized);
    out = storage_of(object->output_storage);
    assert(keyboard_u32(out->data, 0) == 1);
    object->arg = 0x14; /* Offline HTML has a web return structure, not controller data. */
    library_applet_accessor_command(&message, 101, session);
    const uint32_t web_object = message.w[message.payload + 4];
    assert(web_object && web_object <= DOMAIN_SLOTS);
    HostStorage *web = storage_of(g_domain[web_object - 1].arg);
    assert(web && web->size == 0x1010 && keyboard_u32(web->data, 0) == 2);
    object->arg = 0x10; /* Profile selector returns a result and the persistent local UID. */
    library_applet_accessor_command(&message, 101, session);
    const uint32_t profile_object = message.w[message.payload + 4];
    assert(profile_object && profile_object <= DOMAIN_SLOTS);
    HostStorage *profile = storage_of(g_domain[profile_object - 1].arg);
    assert(profile && profile->size == 0x18 && keyboard_u32(profile->data, 0) == 0);
    assert(memcmp(profile->data + 8, g_local_user, sizeof g_local_user) == 0);
    puts("PASS keyboard UTF16/UTF8, text check, cancellation and completion event");
    return 0;
}
