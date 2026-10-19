#define D3_WITH_GPU 1
#include "../host/d3_nvdrv.c"
void d3_gpu_begin_cpu_write(uint64_t address, uint64_t size) { (void)address; (void)size; }
void d3_gpu_end_cpu_write(void) {}

#include <stdio.h>

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

static uint64_t g_test_gpu_address;
static uint64_t g_test_cpu_address;
static uint64_t g_test_mapping_size;
static uint64_t g_test_kind_offset;
static uint32_t g_test_kind;
static uint32_t g_test_maps;
static uint32_t g_test_rekinds;
static uint32_t g_test_map_error;
static uint32_t g_test_submissions;

uint32_t d3_gpu_nv_submit(uint32_t channel, const uint64_t *entries, uint32_t count,
                         uint32_t flags, uint32_t wait_id, uint32_t wait_value, uint32_t signal_id) {
    (void)flags;
    (void)wait_id;
    (void)wait_value;
    if (channel != 1 || count != 1 || entries[0] != 0x1234 || !signal_id)
        return 11;
    g_test_submissions++;
    return 0;
}

uint32_t d3_gpu_nv_as_create(uint32_t big_page) {
    return big_page == 0x20000 ? 1 : 0;
}

uint32_t d3_gpu_nv_map(uint32_t space, uint64_t gpu_address, uint64_t cpu_address,
                      uint64_t size, uint32_t kind) {
    if (space != 1)
        return 11;
    if (g_test_map_error)
        return g_test_map_error;
    g_test_gpu_address = gpu_address;
    g_test_cpu_address = cpu_address;
    g_test_mapping_size = size;
    g_test_kind = kind;
    g_test_maps++;
    return 0;
}

uint32_t d3_gpu_nv_rekind(uint32_t space, uint64_t gpu_address, uint64_t offset,
                         uint64_t size, uint32_t kind) {
    if (space != 1 || gpu_address != g_test_gpu_address ||
        offset > g_test_mapping_size || size > g_test_mapping_size - offset)
        return 11;
    g_test_kind_offset = offset;
    g_test_kind = kind;
    g_test_rekinds++;
    return 0;
}

uint32_t d3_gpu_nv_unmap(uint32_t space, uint64_t gpu_address, uint64_t size) {
    return space == 1 && gpu_address == g_test_gpu_address && size == g_test_mapping_size ? 0 : 11;
}

void d3_gpu_nv_as_close(uint32_t space) {
    (void)space;
}

uint32_t d3_gpu_nv_channel_create(void) {
    return 1;
}

uint32_t d3_gpu_nv_channel_bind(uint32_t channel, uint32_t space) {
    return channel == 1 && space == 1 ? 0 : 11;
}

uint32_t d3_gpu_nv_channel_init(uint32_t channel) {
    return channel == 1 ? 0 : 11;
}

void d3_gpu_nv_channel_close(uint32_t channel) {
    (void)channel;
}

int main(void) {
    uint32_t map_fd, space_fd;
    CHECK(d3_nv_open(1, "/dev/nvmap", &map_fd) == 0);
    CHECK(d3_nv_open(1, "/dev/nvhost-as-gpu", &space_fd) == 0);
    uint32_t initialize[10] = {1, 0, 0x20000};
    CHECK(d3_nv_ioctl(1, space_fd, 0x40284109u, initialize, sizeof initialize, NULL, 0) == 0);
    uint32_t create[2] = {0x40000};
    CHECK(d3_nv_ioctl(1, map_fd, 0xc0080101u, create, sizeof create, NULL, 0) == 0);
    const uint32_t handle = create[1];
    uint32_t allocate[8] = {handle, 0, 0, 0x20000, 0, 0, 0x10000000};
    CHECK(d3_nv_ioctl(1, map_fd, 0xc0200104u, allocate, sizeof allocate, NULL, 0) == 0);
    uint32_t map[10] = {0, 0, handle, 0, 0, 0, 0x40000};
    g_test_map_error = 9;
    CHECK(d3_nv_ioctl(1, space_fd, 0xc0284106u, map, sizeof map, NULL, 0) == 9);
    CHECK(nv_mapping(handle)->references == 1 && g_test_maps == 0);
    g_test_map_error = 0;
    CHECK(d3_nv_ioctl(1, space_fd, 0xc0284106u, map, sizeof map, NULL, 0) == 0);
    CHECK(g_test_maps == 1 && g_test_cpu_address == 0x10000000 && g_test_mapping_size == 0x40000);
    CHECK(nv_mapping(handle)->references == 2);
    uint32_t channel;
    CHECK(d3_nv_open(1, "/dev/nvhost-gpu", &channel) == 0);
    uint32_t bind[1] = {channel};
    CHECK(d3_nv_ioctl(1, space_fd, 0x40044101u, bind, sizeof bind, NULL, 0) == 0);
    uint32_t cull[4] = {0, 0, 2};
    memcpy(cull, &g_test_gpu_address, 8);
    CHECK(d3_nv_ioctl(1, channel, 0xc010480bu, cull, sizeof cull, NULL, 0) == 0);
    CHECK(g_descriptors[channel - 1].zcull_address == g_test_gpu_address);
    uint32_t fifo[8] = {1024, 1};
    CHECK(d3_nv_ioctl(1, channel, 0xc020481au, fifo, sizeof fifo, NULL, 0) == 0);
    uint32_t submit[6] = {0, 0, 1, 0x104, 0, 1};
    const uint64_t entries[1] = {0x1234};
    CHECK(d3_nv_submit(2, channel, submit, entries, sizeof entries) == 11);
    CHECK(d3_nv_submit(1, channel, submit, entries, 4) == 10);
    CHECK(d3_nv_submit(1, channel, submit, entries, sizeof entries) == 0);
    CHECK(submit[3] == 0 && submit[4] == fifo[3] && submit[5] == 1 && g_test_submissions == 1);
    cull[1] = 0xff;
    CHECK(d3_nv_ioctl(1, channel, 0xc010480bu, cull, sizeof cull, NULL, 0) == 9);
    CHECK(d3_nv_close(1, channel) == 0);
    uint32_t remap[10] = {0x100, 0xdb, 0, 0, 0x10000, 0, 0x20000};
    memcpy(remap + 8, &g_test_gpu_address, 8);
    CHECK(d3_nv_ioctl(1, space_fd, 0xc0284106u, remap, sizeof remap, NULL, 0) == 0);
    CHECK(g_test_rekinds == 1 && g_test_kind == 0xdb && g_test_kind_offset == 0x10000);
    CHECK(nv_mapping(handle)->references == 2 && g_test_maps == 1);
    remap[6] = 0x40000;
    CHECK(d3_nv_ioctl(1, space_fd, 0xc0284106u, remap, sizeof remap, NULL, 0) == 11);
    remap[6] = 0x1000;
    remap[8] += 0x1000;
    CHECK(d3_nv_ioctl(1, space_fd, 0xc0284106u, remap, sizeof remap, NULL, 0) == 11);
    uint32_t unmap[2];
    memcpy(unmap, &g_test_gpu_address, 8);
    CHECK(d3_nv_ioctl(1, space_fd, 0x40084105u, unmap, sizeof unmap, NULL, 0) == 0);
    CHECK(nv_mapping(handle)->references == 1);
    CHECK(d3_nv_close(1, space_fd) == 0 && d3_nv_close(1, map_fd) == 0);
    puts("PASS: GPU bridge map failure rollback, alias metadata, kind-only partial remap and pin lifetime");
    return 0;
}
