#include "../host/d3_service.c"

void d3_trace_guest(const char *tag, const d3_saved *saved) {
    (void)tag;
    (void)saved;
}

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

typedef struct {
    uint32_t words[MESSAGE_WORDS] __attribute__((aligned(16)));
} Buffer;

static size_t request(Buffer *buffer, uint32_t type, uint32_t command,
                      uint32_t object, int send_pid) {
    memset(buffer, 0, sizeof *buffer);
    buffer->words[0] = type;
    buffer->words[1] = send_pid ? 0x80000018u : 0x18u;
    if (send_pid)
        buffer->words[2] = 1;
    size_t payload = send_pid ? 8 : 4;
    if (object) {
        buffer->words[payload] = 0x180001u;
        buffer->words[payload + 1] = object;
        payload += 4;
    }
    buffer->words[payload] = CMIF_IN;
    buffer->words[payload + 1] = 1;
    buffer->words[payload + 2] = command;
    buffer->words[payload + 3] = 0x12345678u;
    return payload;
}

static uint64_t dispatch(Buffer *buffer, uint32_t session) {
    d3_saved saved = {0};
    saved.x[0] = session;
    d3_svc_send_sync_request(&saved, (uint64_t)(uintptr_t)buffer->words);
    return saved.x[0];
}

static int plain_resource(void) {
    Buffer buffer;
    const uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "hid", PORT_HID);
    CHECK(session != 0);
    size_t payload = request(&buffer, 6, 0, 0, 1);
    buffer.words[payload + 4] = 0xabcdef01u;
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[0] == 6);
    CHECK((buffer.words[1] & 0x80000000u) != 0);
    CHECK(buffer.words[2] == 0x20u);
    CHECK(buffer.words[4] == CMIF_OUT);
    CHECK(buffer.words[6] == 0);
    CHECK(buffer.words[7] == 0x12345678u);
    CHECK(buffer.words[8] == 0);
    const uint32_t resource = buffer.words[3];
    CHECK(d3_handle_kind(resource) == D3_OBJ_SESSION);
    CHECK(d3_handle_arg(resource) == PORT_HID_APPLET_RESOURCE);

    request(&buffer, 6, 0, 0, 0);
    CHECK(dispatch(&buffer, resource) == 0);
    CHECK(buffer.words[2] == 2u);
    CHECK(buffer.words[4] == CMIF_OUT);
    CHECK(buffer.words[6] == 0);
    const uint32_t memory = buffer.words[3];
    CHECK(d3_handle_kind(memory) == D3_OBJ_SHARED_MEM);
    CHECK(d3_handle_arg(memory) == 0x40000u);
    CHECK(memory != resource);

    request(&buffer, 6, 99, 0, 0);
    CHECK(dispatch(&buffer, resource) == 0);
    CHECK((buffer.words[1] & 0x80000000u) == 0);
    CHECK(buffer.words[4] == CMIF_OUT);
    CHECK(buffer.words[6] != 0);

    memset(&buffer, 0, sizeof buffer);
    buffer.words[0] = 2;
    CHECK(dispatch(&buffer, resource) == 0);
    CHECK(d3_handle_kind(resource) == D3_OBJ_NONE);
    CHECK(d3_handle_kind(memory) == D3_OBJ_SHARED_MEM);
    CHECK(d3_handle_close(memory) == 0);
    CHECK(d3_handle_close(session) == 0);
    return 0;
}

static int domain_resource(void) {
    Buffer buffer;
    const uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "hid", PORT_HID);
    CHECK(session != 0);
    request(&buffer, 7, 0, 0, 0);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[4] == CMIF_OUT);
    CHECK(buffer.words[6] == 0);
    const uint32_t root = buffer.words[8];
    CHECK(domain_iface(session, root) == D3_IF_HID);

    size_t payload = request(&buffer, 6, 0, root, 1);
    buffer.words[payload + 4] = 0xabcdef01u;
    CHECK(dispatch(&buffer, session) == 0);
    CHECK((buffer.words[1] & 0x80000000u) == 0);
    CHECK(buffer.words[4] == 1);
    CHECK(buffer.words[8] == CMIF_OUT);
    CHECK(buffer.words[10] == 0);
    const uint32_t resource = buffer.words[12];
    CHECK(domain_iface(session, resource) == D3_IF_HID_APPLET_RESOURCE);

    request(&buffer, 6, 0, resource, 0);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[2] == 2u);
    CHECK(buffer.words[4] == 0);
    CHECK(buffer.words[8] == CMIF_OUT);
    CHECK(buffer.words[10] == 0);
    const uint32_t memory = buffer.words[3];
    CHECK(d3_handle_kind(memory) == D3_OBJ_SHARED_MEM);
    CHECK(d3_handle_arg(memory) == 0x40000u);
    CHECK(d3_handle_close(session) == 0);
    CHECK(domain_iface(session, root) == D3_IF_NONE);
    CHECK(domain_iface(session, resource) == D3_IF_NONE);
    CHECK(d3_handle_kind(memory) == D3_OBJ_SHARED_MEM);
    CHECK(d3_handle_close(memory) == 0);
    return 0;
}

static int controller_result_buffer(void) {
    Buffer buffer;
    const uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", PORT_UNKNOWN);
    CHECK(session != 0);
    const uint32_t accessor = domain_add(session, D3_IF_LIBRARY_APPLET_ACCESSOR);
    CHECK(accessor != 0);
    g_domain[accessor - 1].arg = 0xc;
    request(&buffer, 6, 101, accessor, 0);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[10] == 0);
    const uint32_t storage = buffer.words[12];
    CHECK(domain_iface(session, storage) == D3_IF_STORAGE);
    request(&buffer, 6, 0, storage, 0);
    CHECK(dispatch(&buffer, session) == 0);
    const uint32_t storage_accessor = buffer.words[12];
    CHECK(domain_iface(session, storage_accessor) == D3_IF_STORAGE_ACCESSOR);

    uint32_t output[4] = {0xdeadbeefu, 0xdeadbeefu, 0xdeadbeefu, 0xdeadbeefu};
    const uint64_t address = (uint64_t)(uintptr_t)output;
    memset(&buffer, 0, sizeof buffer);
    buffer.words[0] = 0x01000006u;
    buffer.words[1] = 0xc0fu;
    buffer.words[8] = 0x180001u;
    buffer.words[9] = storage_accessor;
    buffer.words[12] = CMIF_IN;
    buffer.words[13] = 1;
    buffer.words[14] = 11;
    buffer.words[19] = 12;
    buffer.words[20] = (uint32_t)address;
    buffer.words[21] = (12u << 16) | (uint32_t)(address >> 32);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[10] == 0);
    CHECK(output[0] == 1);
    CHECK(output[1] == 0);
    CHECK(output[2] == 0);
    CHECK(output[3] == 0xdeadbeefu);

    memset(&buffer, 0, sizeof buffer);
    buffer.words[0] = 0x01000006u;
    buffer.words[1] = (15u << 10) | 55u;
    buffer.words[8] = CMIF_IN;
    buffer.words[9] = 1;
    Message message = {0};
    CHECK(message_parse(&message, (uint64_t)(uintptr_t)buffer.words) == 0);
    uint64_t decoded_address = 0;
    size_t decoded_size = 0;
    CHECK(message_buffer(&message, &decoded_address, &decoded_size) == 0);
    CHECK(d3_handle_close(session) == 0);
    return 0;
}

static int allocation_failure(void) {
    Buffer buffer;
    const uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "hid", PORT_HID);
    const uint32_t resource =
        d3_handle_alloc(D3_OBJ_SESSION, "hid-applet", PORT_HID_APPLET_RESOURCE);
    CHECK(session != 0 && resource != 0);
    while (d3_handle_alloc(D3_OBJ_EVENT, "test-full", 0) != 0) {
    }
    request(&buffer, 6, 0, 0, 1);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK((buffer.words[1] & 0x80000000u) == 0);
    CHECK(buffer.words[4] == CMIF_OUT);
    CHECK(buffer.words[6] != 0);
    request(&buffer, 6, 0, 0, 0);
    CHECK(dispatch(&buffer, resource) == 0);
    CHECK((buffer.words[1] & 0x80000000u) == 0);
    CHECK(buffer.words[4] == CMIF_OUT);
    CHECK(buffer.words[6] != 0);
    return 0;
}

int main(void) {
    g_log_tried = 1;
    g_log = -1;
    CHECK(plain_resource() == 0);
    CHECK(domain_resource() == 0);
    CHECK(controller_result_buffer() == 0);
    CHECK(allocation_failure() == 0);
    puts("PASS: HID session/domain, copy shared memory, reply PID, close, controller result C buffer and allocation errors");
    return 0;
}
