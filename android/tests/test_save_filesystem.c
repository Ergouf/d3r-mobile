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
} FsRequest;

static void request(FsRequest *buffer, uint32_t object, uint32_t command) {
    memset(buffer, 0, sizeof *buffer);
    buffer->words[0] = 6;
    buffer->words[1] = 0x1e;
    buffer->words[4] = 0x580001u;
    buffer->words[5] = object;
    buffer->words[8] = CMIF_IN;
    buffer->words[9] = 1;
    buffer->words[10] = command;
    buffer->words[11] = 0x12345678;
}

static uint32_t dispatch(FsRequest *buffer, uint32_t session) {
    d3_saved saved = {0};
    saved.x[0] = session;
    d3_svc_send_sync_request(&saved, (uint64_t)(uintptr_t)buffer->words);
    return (uint32_t)saved.x[0];
}

int main(void) {
    g_log_tried = 1;
    g_log = -1;
    CHECK(mkdir(D3_DATA_ROOT, 0700) == 0 || errno == EEXIST);
    const uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "fsp-srv", PORT_FSP);
    const uint32_t root = domain_add(session, D3_IF_FSP_SRV);
    CHECK(session != 0 && root != 0);
    FsRequest buffer;
    request(&buffer, root, 1005);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[10] == 0 && buffer.words[12] == 0);
    request(&buffer, root, 1011);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[12] == 2 && buffer.words[13] == 0);
    request(&buffer, root, 1004);
    buffer.words[12] = 2;
    CHECK(dispatch(&buffer, session) == 0);
    request(&buffer, root, 1005);
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[12] == 2);
    request(&buffer, root, 51);
    buffer.words[4] = 0x100001u;
    CHECK(dispatch(&buffer, session) == 0 && buffer.words[10] == D3_RESULT(2, 1));
    request(&buffer, root, 51);
    buffer.words[12] = 1;
    buffer.words[16] = (uint32_t)getpid();
    buffer.words[22] = 1;
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[10] == 0);
    const uint32_t filesystem = buffer.words[12];
    CHECK(domain_iface(session, filesystem) == D3_IF_SAVE_FILESYSTEM);
    const int descriptor = (int)g_domain[filesystem - 1].arg;
    CHECK(fcntl(descriptor, F_GETFD) >= 0);
    char leaf[0x301];
    CHECK(save_parent(descriptor, "../outside", leaf) < 0);
    CHECK(save_parent(descriptor, "/../outside", leaf) < 0);
    CHECK(mkdirat(descriptor, "subdir", 0700) == 0);
    int subparent = save_parent(descriptor, "/subdir/file.dat", leaf);
    CHECK(subparent >= 0 && strcmp(leaf, "file.dat") == 0);
    CHECK(close(subparent) == 0);
    CHECK(symlinkat("/data/local/tmp", descriptor, "escape") == 0);
    CHECK(save_parent(descriptor, "escape/file.dat", leaf) < 0);
    CHECK(unlinkat(descriptor, "escape", 0) == 0);
    CHECK(unlinkat(descriptor, "subdir", AT_REMOVEDIR) == 0);
    const int file = openat(descriptor, "persistent.txt", O_RDWR | O_CREAT | O_EXCL, 0600);
    CHECK(file >= 0);
    CHECK(write(file, "saved", 5) == 5);
    CHECK(close(file) == 0);
    request(&buffer, filesystem, 10);
    CHECK(dispatch(&buffer, session) == 0 && buffer.words[10] == 0);
    request(&buffer, filesystem, 11);
    CHECK(dispatch(&buffer, session) == 0 && buffer.words[10] == 0);
    uint64_t free_bytes;
    memcpy(&free_bytes, &buffer.words[12], sizeof free_bytes);
    CHECK(free_bytes > 0);
    domain_close(session, filesystem);
    CHECK(fcntl(descriptor, F_GETFD) < 0 && errno == EBADF);
    request(&buffer, root, 51);
    buffer.words[12] = 1;
    buffer.words[16] = (uint32_t)getpid();
    buffer.words[22] = 1;
    CHECK(dispatch(&buffer, session) == 0 && buffer.words[10] == 0);
    const uint32_t reopened = buffer.words[12];
    const int reopened_descriptor = (int)g_domain[reopened - 1].arg;
    const int persisted = openat(reopened_descriptor, "persistent.txt", O_RDONLY);
    CHECK(persisted >= 0);
    char data[5];
    CHECK(read(persisted, data, sizeof data) == 5);
    CHECK(memcmp(data, "saved", 5) == 0);
    CHECK(close(persisted) == 0);
    CHECK(unlinkat(reopened_descriptor, "persistent.txt", 0) == 0);
    request(&buffer, root, 1003);
    CHECK(dispatch(&buffer, session) == 0);
    request(&buffer, root, 51);
    buffer.words[12] = 1;
    buffer.words[16] = (uint32_t)getpid();
    buffer.words[18] = 0xdeadbeef;
    buffer.words[22] = 1;
    CHECK(dispatch(&buffer, session) == 0);
    CHECK(buffer.words[10] == D3_RESULT(2, 1002));
    CHECK(d3_handle_close(session) == 0);
    CHECK(fcntl(reopened_descriptor, F_GETFD) < 0 && errno == EBADF);
    puts("PASS: save filesystem auto-creation, persistent contents, commit, capacity, close and access-log ABI");
    return 0;
}
