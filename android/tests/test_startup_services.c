#define D3_CONTENT_ROOT D3_DATA_ROOT "/aoc-test-content"
#include "../host/d3_service.c"

void d3_trace_guest(const char *tag, const d3_saved *saved) {
    (void)tag;
    (void)saved;
}

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

typedef struct {
    uint32_t words[MESSAGE_WORDS] __attribute__((aligned(16)));
} RequestBuffer;

static size_t request(RequestBuffer *buffer, uint32_t object, uint32_t command,
                       size_t argument_bytes, const void *input, size_t input_size,
                       void *output, size_t output_size, void *inline_output, size_t inline_size) {
    memset(buffer, 0, sizeof *buffer);
    const uint64_t source = (uint64_t)(uintptr_t)input;
    const size_t descriptor_end = source ? 4u : 2u;
    buffer->words[0] = 6u | (source ? 0x10000u : 0u);
    if (source) {
        buffer->words[2] = (uint32_t)(input_size << 16u) | (uint32_t)((source >> 32u) & 15u) << 12u |
                           (uint32_t)((source >> 36u) & 7u) << 6u;
        buffer->words[3] = (uint32_t)source;
    }
    const size_t frame = 4u;
    const size_t magic = frame + (object ? 4u : 0u);
    const size_t end = magic + 4u + (argument_bytes + 3u) / 4u;
    buffer->words[1] = (uint32_t)(end - descriptor_end);
    if (object) {
        buffer->words[frame] = 1u | (uint32_t)((16u + argument_bytes) << 16u);
        buffer->words[frame + 1u] = object;
    }
    buffer->words[magic] = CMIF_IN;
    buffer->words[magic + 1u] = 1;
    buffer->words[magic + 2u] = command;
    buffer->words[magic + 3u] = 0x1234;
    if (output) {
        const uint64_t destination = (uint64_t)(uintptr_t)output;
        buffer->words[1] |= (inline_output ? 4u : 3u) << 10u;
        buffer->words[end] = (uint32_t)destination;
        buffer->words[end + 1u] = (uint32_t)(destination >> 32u) | (uint32_t)(output_size << 16u);
        if (inline_output) {
            const uint64_t inlined = (uint64_t)(uintptr_t)inline_output;
            buffer->words[end + 2u] = (uint32_t)inlined;
            buffer->words[end + 3u] = (uint32_t)(inlined >> 32u) | (uint32_t)(inline_size << 16u);
        }
    }
    return magic + 4u;
}

static uint32_t dispatch(RequestBuffer *buffer, uint32_t session) {
    d3_saved saved = {0};
    saved.x[0] = session;
    d3_svc_send_sync_request(&saved, (uint64_t)(uintptr_t)buffer->words);
    return (uint32_t)saved.x[0];
}

static int exercise_vi(void) {
    RequestBuffer buffer;
    const uint32_t display = d3_handle_alloc(D3_OBJ_SESSION, "vi-app", PORT_VI_APP);
    uint32_t parcel[128] = {0};
    request(&buffer, 0, 2030, 16, NULL, 0, parcel, sizeof parcel, NULL, 0);
    CHECK(dispatch(&buffer, display) == 0 && buffer.words[6] == 0);
    CHECK(parcel[0] == 40 && parcel[1] == 16 && parcel[2] == 4 && parcel[3] == 56);
    CHECK(parcel[4] == 2 && parcel[5] == 1 && parcel[6] == 1);
    CHECK(memcmp(parcel + 10, "dispdrv", 8) == 0);
    CHECK(buffer.words[8] == 1 && buffer.words[10] == 60);
    request(&buffer, 0, 2030, 16, NULL, 0, parcel, 32, NULL, 0);
    CHECK(dispatch(&buffer, display) == 0 && buffer.words[6] != 0);
    request(&buffer, 0, 100, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, display) == 0 && buffer.words[6] == 0);
    const uint32_t binder = buffer.words[3];
    CHECK(d3_handle_arg(binder) == PORT_BINDER && port_iface("dispdrv") == D3_IF_BINDER);
    size_t arguments = request(&buffer, 0, 1, 12, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 1;
    buffer.words[arguments + 2] = 1;
    CHECK(dispatch(&buffer, binder) == 0 && buffer.words[6] == 0 && g_vi_refs[1] == 1);
    arguments = request(&buffer, 0, 1, 12, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = (uint32_t)-2;
    buffer.words[arguments + 2] = 1;
    CHECK(dispatch(&buffer, binder) == 0 && buffer.words[6] != 0 && g_vi_refs[1] == 1);
    memset(parcel, 0, sizeof parcel);
    static const char token[] = "android.gui.IGraphicBufferProducer";
    const size_t token_end = (8u + sizeof token * 2u + 3u) & ~3u;
    parcel[0] = (uint32_t)token_end + 12;
    parcel[1] = 16;
    parcel[3] = 16 + parcel[0];
    parcel[5] = sizeof token - 1;
    for (size_t index = 0; index < sizeof token; index++)
        ((uint16_t *)(parcel + 6))[index] = (uint8_t)token[index];
    uint32_t *values = parcel + 4 + token_end / 4;
    uint32_t output[128] = {0};
    values[0] = 0;
    values[1] = 1;
    values[2] = 0;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 10;
    CHECK(dispatch(&buffer, binder) == 0 && buffer.words[6] == 0);
    CHECK(output[0] == 20 && output[4] == 1280 && output[5] == 720 && output[8] == 0);
    CHECK(g_vi_api == 1);
    arguments = request(&buffer, 0, 3, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 9;
    CHECK(dispatch(&buffer, binder) == 0 && buffer.words[6] == 0);
    CHECK(output[0] == 8 && output[4] == 1280 && output[5] == 0);
    uint32_t nvmap_descriptor = 0;
    CHECK(d3_nv_open(77, "/dev/nvmap", &nvmap_descriptor) == 0);
    uint32_t create[2] = {0x800000, 0};
    CHECK(d3_nv_ioctl(77, nvmap_descriptor, 0xc0080101u, create, sizeof create, NULL, 0) == 0);
    const uint32_t nvmap_id = create[1];
    uint32_t allocate[8] = {nvmap_id, 0, 0, 4096, 0, 0, 0x12300000, 0};
    CHECK(d3_nv_ioctl(77, nvmap_descriptor, 0xc0200104u, allocate, sizeof allocate, NULL, 0) == 0);
    memset(values, 0, 380);
    values[1] = 1;
    values[2] = 364;
    values[5] = 1600;
    values[6] = 900;
    values[7] = 1600;
    values[8] = 1;
    values[15] = nvmap_id;
    values[22] = 1;
    parcel[0] = (uint32_t)token_end + 380;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 14;
    CHECK(dispatch(&buffer, binder) == 0 && output[4] == 0);
    CHECK(g_vi_buffers[0].populated && g_vi_buffers[0].data[11] == nvmap_id);
    uint32_t release[6] = {nvmap_id};
    CHECK(d3_nv_ioctl(77, nvmap_descriptor, 0xc0180105u, release, sizeof release, NULL, 0) == 0);
    uint32_t query[3] = {nvmap_id, 1, 0};
    CHECK(d3_nv_ioctl(77, nvmap_descriptor, 0xc00c0109u, query, sizeof query, NULL, 0) == 0);
    CHECK(query[2] == 0x800000);
    memset(values, 0, 380);
    parcel[0] = (uint32_t)token_end + 20;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 3;
    CHECK(dispatch(&buffer, binder) == 0 && output[4] == 0 && output[17] == 1);
    CHECK(output[5] == 1 && output[6] == 36 && output[8] == 0 && output[9] == UINT32_MAX);
    CHECK(g_vi_buffers[0].dequeued);
    parcel[0] = (uint32_t)token_end + 4;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 1;
    CHECK(dispatch(&buffer, binder) == 0 && output[98] == 0);
    CHECK(output[4] == 1 && output[5] == 364 && output[8] == 1600 && output[18] == nvmap_id);
    parcel[0] = (uint32_t)token_end + 48;
    values[1] = 36;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 8;
    CHECK(dispatch(&buffer, binder) == 0 && output[4] == 0 && !g_vi_buffers[0].dequeued);
    parcel[0] = (uint32_t)token_end + 4;
    values[0] = 1;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 11;
    CHECK(dispatch(&buffer, binder) == 0 && output[4] == 0 && !g_vi_api);
    CHECK(!g_vi_buffers[0].populated);
    CHECK(d3_nv_ioctl(77, nvmap_descriptor, 0xc00c0109u, query, sizeof query, NULL, 0) == 11);
    CHECK(d3_nv_close(77, nvmap_descriptor) == 0);
    parcel[1] = UINT32_MAX;
    arguments = request(&buffer, 0, 0, 12, parcel, sizeof parcel, output, sizeof output, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 9;
    CHECK(dispatch(&buffer, binder) == 0 && buffer.words[6] != 0);
    g_vi_api = 0;
    puts("PASS: VI parcel, Binder refs/connect/query, nvmap pins, preallocate/dequeue/request/cancel/disconnect and bounds");
    return 0;
}

int main(void) {
    g_log_tried = 1;
    g_log = -1;
    CHECK(exercise_vi() == 0);
    const uint32_t aoc = d3_handle_alloc(D3_OBJ_SESSION, "aoc:u", PORT_AOC);
    RequestBuffer aoc_request;
    size_t handle_count = 0;
    for (size_t index = 0; index < HANDLE_SLOTS; index++)
        handle_count += g_obj[index].kind != D3_OBJ_NONE;
    for (size_t iteration = 0; iteration < 1000; iteration++) {
        request(&aoc_request, 0, 2, 8, NULL, 0, NULL, 0, NULL, 0);
        CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[6] == 0);
        CHECK(!(aoc_request.words[1] >> 31) && aoc_request.words[8] == 0);
    }
    size_t after_count = 0;
    for (size_t index = 0; index < HANDLE_SLOTS; index++)
        after_count += g_obj[index].kind != D3_OBJ_NONE;
    CHECK(handle_count == after_count);
    request(&aoc_request, 0, 8, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[2] == 2);
    CHECK(d3_handle_kind(aoc_request.words[3]) == D3_OBJ_EVENT);
    CHECK(d3_handle_close(aoc_request.words[3]) == 0);
    puts("PASS: AOC cmd2 returns a zero count without leaking handles; cmd8 returns a copy event");
    mkdir(D3_DATA_ROOT, 0700);
    mkdir(D3_CONTENT_ROOT, 0700);
    mkdir(D3_CONTENT_ROOT "/AddOnContent", 0700);
    mkdir(D3_CONTENT_ROOT "/AddOnContent/11", 0700);
    request(&aoc_request, 0, 2, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[8] == 0);
    FILE *marker = fopen(D3_CONTENT_ROOT "/AddOnContent/11/.d3-content-complete", "we");
    CHECK(marker && fputs("01001b300b9bf00b\n", marker) >= 0 && fclose(marker) == 0);
    request(&aoc_request, 0, 2, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[8] == 1);
    unsigned addons[2] = {0xdead, 0xbeef};
    size_t aoc_arguments = request(&aoc_request, 0, 3, 16, NULL, 0, addons, sizeof addons, NULL, 0);
    aoc_request.words[aoc_arguments] = 0; aoc_request.words[aoc_arguments + 1] = 2;
    CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[6] == 0 && aoc_request.words[8] == 1);
    CHECK(addons[0] == 11 && addons[1] == 0xbeef);
    aoc_arguments = request(&aoc_request, 0, 3, 16, NULL, 0, addons, sizeof addons, NULL, 0);
    aoc_request.words[aoc_arguments] = 2; aoc_request.words[aoc_arguments + 1] = 1;
    CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[6] != 0);
    aoc_arguments = request(&aoc_request, 0, 7, 16, NULL, 0, NULL, 0, NULL, 0);
    aoc_request.words[aoc_arguments] = 11;
    CHECK(dispatch(&aoc_request, aoc) == 0 && aoc_request.words[6] == 0);
    CHECK(unlink(D3_CONTENT_ROOT "/AddOnContent/11/.d3-content-complete") == 0);
    CHECK(rmdir(D3_CONTENT_ROOT "/AddOnContent/11") == 0);
    CHECK(rmdir(D3_CONTENT_ROOT "/AddOnContent") == 0);
    CHECK(rmdir(D3_CONTENT_ROOT) == 0);
    RequestBuffer buffer;
    const uint32_t account = d3_handle_alloc(D3_OBJ_SESSION, "acc:u0", PORT_ACCOUNT);
    const uint32_t root = domain_add(account, D3_IF_ACCOUNT);
    request(&buffer, root, 50, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, account) == 0 && buffer.words[10] == 0 && buffer.words[12] == 0);
    size_t arguments = request(&buffer, root, 1, 16, NULL, 0, NULL, 0, NULL, 0);
    memcpy(buffer.words + arguments, g_local_user, sizeof g_local_user);
    CHECK(dispatch(&buffer, account) == 0 && buffer.words[10] == 0 && buffer.words[12] == 1);
    request(&buffer, root, 1, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, account) == 0 && buffer.words[10] != 0);
    uint64_t users[16];
    memset(users, 0xff, sizeof users);
    request(&buffer, root, 141, 0, NULL, 0, users, sizeof users, NULL, 0);
    CHECK(dispatch(&buffer, account) == 0 && buffer.words[10] == 0);
    CHECK(memcmp(users, g_local_user, sizeof g_local_user) == 0 && users[2] == 0 && users[15] == 0);
    arguments = request(&buffer, root, 101, 16, NULL, 0, NULL, 0, NULL, 0);
    memcpy(buffer.words + arguments, g_local_user, sizeof g_local_user);
    CHECK(dispatch(&buffer, account) == 0 && buffer.words[10] == 0);
    const uint32_t manager = buffer.words[12];
    request(&buffer, manager, 0, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, account) == 0 && buffer.words[10] == D3_RESULT(124, 200));
    const uint32_t applet = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", port_kind("appletOE"));
    const uint32_t application = domain_add(applet, D3_IF_APPLICATION_FUNCTIONS);
    arguments = request(&buffer, application, 1, 4, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 1;
    CHECK(dispatch(&buffer, applet) == 0 && buffer.words[10] == D3_RESULT(128, 2));
    arguments = request(&buffer, application, 1, 4, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 2;
    CHECK(dispatch(&buffer, applet) == 0 && buffer.words[10] == 0);
    const uint32_t storage_object_id = buffer.words[12];
    const HostStorage *storage = storage_of(g_domain[storage_object_id - 1].arg);
    CHECK(storage && storage->size == 0x88);
    uint32_t header[2];
    memcpy(header, storage->data, sizeof header);
    CHECK(header[0] == 0xc79497ca && header[1] == 1);
    CHECK(memcmp(storage->data + 8, g_local_user, sizeof g_local_user) == 0);
    arguments = request(&buffer, application, 1, 4, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 2;
    CHECK(dispatch(&buffer, applet) == 0 && buffer.words[10] == D3_RESULT(128, 2));
    const uint32_t nv = d3_handle_alloc(D3_OBJ_SESSION, "nvdrv", PORT_NVDRV);
    request(&buffer, application, 40, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, applet) == 0 && buffer.words[10] == 0 && buffer.words[12] == 1);
    request(&buffer, application, 40, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, applet) == 0 && buffer.words[10] == 0 && buffer.words[12] == 0);
    const char path[] = "/dev/nvhost-ctrl-gpu";
    request(&buffer, 0, 0, 0, path, sizeof path, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, nv) == 0 && buffer.words[4] == CMIF_OUT && buffer.words[6] == 0);
    const uint32_t descriptor = buffer.words[8];
    CHECK(descriptor != 0 && buffer.words[9] == 0);
    uint32_t parameters[44] = {0};
    uint32_t output[44] = {0};
    uint32_t inlined[40] = {0};
    arguments = request(&buffer, 0, 12, 8, parameters, sizeof parameters,
                         output, sizeof output, inlined, sizeof inlined);
    buffer.words[arguments] = descriptor;
    buffer.words[arguments + 1] = 0xc0b04705u;
    CHECK(dispatch(&buffer, nv) == 0 && buffer.words[4] == CMIF_OUT && buffer.words[8] == 0);
    CHECK(output[0] == 160 && output[4] == 0x120 && inlined[23] == 0xb197);
    CHECK(memcmp(output + 4, inlined, sizeof inlined) == 0);
    uint32_t submit_parameters[6] = {0, 0, 1, 0x104, 0, 1};
    const uint64_t submit_entries[1] = {0xfeedface12345678};
    uint32_t submit_output[6] = {0};
    memset(&buffer, 0, sizeof buffer);
    const uint64_t input_pointer = (uint64_t)(uintptr_t)submit_parameters;
    const uint64_t entries_pointer = (uint64_t)(uintptr_t)submit_entries;
    const uint64_t output_pointer = (uint64_t)(uintptr_t)submit_output;
    buffer.words[0] = 6u | (2u << 16u);
    buffer.words[1] = 12u | (3u << 10u);
    buffer.words[2] = (24u << 16u) | (uint32_t)((input_pointer >> 32u) & 15u) << 12u |
                      (uint32_t)((input_pointer >> 36u) & 7u) << 6u;
    buffer.words[3] = (uint32_t)input_pointer;
    buffer.words[4] = (8u << 16u) | 1u | (uint32_t)((entries_pointer >> 32u) & 15u) << 12u |
                      (uint32_t)((entries_pointer >> 36u) & 7u) << 6u;
    buffer.words[5] = (uint32_t)entries_pointer;
    buffer.words[8] = CMIF_IN;
    buffer.words[9] = 1;
    buffer.words[10] = 11;
    buffer.words[12] = descriptor;
    buffer.words[13] = 0xc018481bu;
    buffer.words[18] = (uint32_t)output_pointer;
    buffer.words[19] = (uint32_t)(output_pointer >> 32u) | (24u << 16u);
    CHECK(dispatch(&buffer, nv) == 0 && buffer.words[8] == 11);
    CHECK(submit_entries[0] == UINT64_C(0xfeedface12345678));
    const uint32_t network = d3_handle_alloc(D3_OBJ_SESSION, "nifm:u", port_kind("nifm:u"));
    const uint32_t network_root = domain_add(network, D3_IF_NIFM);
    request(&buffer, network_root, 5, 8, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] == 0);
    const uint32_t general = buffer.words[12];
    CHECK(general && general != network_root && domain_iface(network, general) == D3_IF_NIFM_GENERAL);
    request(&buffer, general, 12, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] == 0 && buffer.words[12] == 0);
    request(&buffer, general, 4, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] != 0);
    arguments = request(&buffer, general, 4, 4, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 2;
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] == 0);
    const uint32_t network_request = buffer.words[12];
    CHECK(domain_iface(network, network_request) == D3_IF_NIFM_REQUEST);
    request(&buffer, network_request, 0, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[12] == 1);
    request(&buffer, network_request, 2, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[2] == 4);
    const uint32_t state_event = buffer.words[3];
    const uint32_t change_event = buffer.words[4];
    CHECK(d3_handle_kind(state_event) == D3_OBJ_EVENT && d3_handle_kind(change_event) == D3_OBJ_EVENT);
    CHECK(state_event != change_event);
    arguments = request(&buffer, network_request, 6, 4, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 2;
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] == 0);
    CHECK(g_domain[network_request - 1].initialized == 2);
    request(&buffer, network_request, 4, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] == 0);
    CHECK(g_domain[network_request - 1].pending == 1 && g_domain[network_request - 1].arg == 1);
    request(&buffer, network_request, 1, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, network) == 0 && buffer.words[10] == D3_RESULT(110, 1111));
    CHECK(d3_handle_close(state_event) == 0 && d3_handle_close(change_event) == 0);
    const uint32_t power = d3_handle_alloc(D3_OBJ_SESSION, "apm", PORT_APM);
    request(&buffer, 0, 0, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, power) == 0 && buffer.words[2] == 0x20 && buffer.words[6] == 0);
    const uint32_t power_session = buffer.words[3];
    CHECK(d3_handle_kind(power_session) == D3_OBJ_SESSION && port_iface(d3_handle_name(power_session)) == D3_IF_APM_SESSION);
    arguments = request(&buffer, 0, 0, 8, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 1;
    buffer.words[arguments + 1] = 0x20004;
    CHECK(dispatch(&buffer, power_session) == 0 && buffer.words[6] == 0);
    arguments = request(&buffer, 0, 1, 4, NULL, 0, NULL, 0, NULL, 0);
    buffer.words[arguments] = 1;
    CHECK(dispatch(&buffer, power_session) == 0 && buffer.words[6] == 0 && buffer.words[8] == 0x20004);
    const uint32_t power_root = domain_add(power, D3_IF_APM);
    request(&buffer, power_root, 0, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, power) == 0 && buffer.words[10] == 0);
    CHECK(domain_iface(power, buffer.words[12]) == D3_IF_APM_SESSION);
    const uint32_t parental = d3_handle_alloc(D3_OBJ_SESSION, "pctl", port_kind("pctl"));
    const uint32_t parental_root = domain_add(parental, D3_IF_PCTL);
    request(&buffer, parental_root, 1, 8, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, parental) == 0 && buffer.words[10] == 0);
    const uint32_t policy = buffer.words[12];
    CHECK(domain_iface(parental, policy) == D3_IF_PCTL_SERVICE && !g_domain[policy - 1].initialized);
    CHECK(g_domain[policy - 1].arg == 0);
    request(&buffer, policy, 1, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, parental) == 0 && buffer.words[10] == 0);
    CHECK(g_domain[policy - 1].initialized);
    request(&buffer, policy, 1001, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, parental) == 0 && buffer.words[10] == 0);
    CHECK(g_domain[policy - 1].arg == 1);
    request(&buffer, parental_root, 1001, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, parental) == 0 && buffer.words[10] != 0);
    const uint32_t nfp = d3_handle_alloc(D3_OBJ_SESSION, "nfp:user", port_kind("nfp:user"));
    const uint32_t nfp_root = domain_add(nfp, port_iface("nfp:user"));
    request(&buffer, nfp_root, 0, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[10] == 0);
    const uint32_t nfp_user = buffer.words[12];
    CHECK(domain_iface(nfp, nfp_user) == D3_IF_NFP_USER);
    uint64_t nfc_devices[8];
    memset(nfc_devices, 0xab, sizeof nfc_devices);
    request(&buffer, nfp_user, 2, 0, NULL, 0, nfc_devices, sizeof nfc_devices, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[10] == D3_RESULT(115, 77));
    request(&buffer, nfp_user, 0, 16, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[10] == 0);
    request(&buffer, nfp_user, 19, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[12] == 1);
    request(&buffer, nfp_user, 2, 0, NULL, 0, nfc_devices, sizeof nfc_devices, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[10] == 0 && buffer.words[12] == 0);
    CHECK(nfc_devices[0] == UINT64_C(0xabababababababab));
    request(&buffer, nfp_user, 1, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[10] == 0);
    request(&buffer, nfp_user, 19, 0, NULL, 0, NULL, 0, NULL, 0);
    CHECK(dispatch(&buffer, nfp) == 0 && buffer.words[12] == 0);
    puts("PASS: account, launch storage, nvdrv, offline NIFM, PCTL, APM, NotifyRunning and no-device NFP");
    return 0;
}
