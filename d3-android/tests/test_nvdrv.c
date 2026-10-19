#include "../host/d3_nvdrv.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

int main(void) {
    uint32_t descriptor;
    CHECK(d3_nv_open(1, "/dev/unknown", &descriptor) == 0x30011u);
    CHECK(descriptor == UINT32_MAX);
    CHECK(d3_nv_open(1, "/dev/nvhost-prof-gpu", &descriptor) == 2);
    CHECK(d3_nv_open(1, "/dev/nvhost-ctrl-gpu", &descriptor) == 0);
    uint32_t characteristics[44] = {0};
    uint32_t inline_output[40] = {0};
    CHECK(d3_nv_ioctl(2, descriptor, 0xc0b04705u, characteristics, sizeof characteristics,
                      inline_output, sizeof inline_output) == 11);
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0b04705u, characteristics, 16, NULL, 0) == 10);
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0b04705u, characteristics, sizeof characteristics,
                      inline_output, sizeof inline_output) == 0);
    CHECK(characteristics[0] == 160 && characteristics[4] == 0x120);
    CHECK(inline_output[0] == 0x120 && inline_output[23] == 0xb197);
    CHECK(memcmp(characteristics + 4, inline_output, sizeof inline_output) == 0);
    CHECK(d3_nv_close(2, descriptor) == 11);
    CHECK(d3_nv_close(1, descriptor) == 0);
    CHECK(d3_nv_close(1, descriptor) == 11);
    CHECK(d3_nv_open(1, "/dev/nvmap", &descriptor) == 0);
    uint32_t create[2] = {8192, 0};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0080101u, create, sizeof create, NULL, 0) == 0);
    const uint32_t handle = create[1];
    CHECK(handle != 0);
    uint32_t allocation[8] = {handle, 0, 0, 0x3000, 0, 0, 0x10001000, 0};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0200104u, allocation, sizeof allocation, NULL, 0) == 11);
    allocation[3] = 0x20000;
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0200104u, allocation, sizeof allocation, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0200104u, allocation, sizeof allocation, NULL, 0) == 6);
    uint32_t parameter[3] = {handle, 1, 0};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc00c0109u, parameter, sizeof parameter, NULL, 0) == 0);
    CHECK(parameter[2] == 8192);
    uint32_t duplicate[2] = {handle, 0};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0080103u, duplicate, sizeof duplicate, NULL, 0) == 0);
    CHECK(duplicate[1] == handle);
    uint32_t release[6] = {handle};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0180105u, release, sizeof release, NULL, 0) == 0);
    CHECK(release[2] == 0x10001000 && release[4] == 8192);
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0180105u, release, sizeof release, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0180105u, release, sizeof release, NULL, 0) == 11);
    uint32_t unknown[2] = {0};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc008017fu, unknown, sizeof unknown, NULL, 0) == 1);
    CHECK(d3_nv_close(1, descriptor) == 0);
    CHECK(d3_nv_open(1, "/dev/nvhost-as-gpu", &descriptor) == 0);
    uint32_t initialize[10] = {1, 0, 0x20000};
    CHECK(d3_nv_ioctl(1, descriptor, 0x40284109u, initialize, sizeof initialize, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, descriptor, 0x40284109u, initialize, sizeof initialize, NULL, 0) == 8);
    uint32_t regions[16] = {0};
    uint64_t region_output[6] = {0};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0404108u, regions, sizeof regions,
                      region_output, sizeof region_output) == 0);
    CHECK(regions[2] == 48 && region_output[0] == 0x8000000);
    CHECK(region_output[1] == 4096 && region_output[4] == 0x20000);
    uint32_t reserve[6] = {8, 4096};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0184102u, reserve, sizeof reserve, NULL, 0) == 0);
    CHECK(reserve[4] == 0x8000000);
    reserve[2] = 1;
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0184102u, reserve, sizeof reserve, NULL, 0) == 11);
    uint32_t free_space[4] = {reserve[4], reserve[5], 8, 4096};
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0104103u, free_space, sizeof free_space, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, descriptor, 0xc0104103u, free_space, sizeof free_space, NULL, 0) == 11);
    uint32_t channel;
    CHECK(d3_nv_open(1, "/dev/nvhost-gpu", &channel) == 0);
    uint32_t bind[1] = {channel};
    CHECK(d3_nv_ioctl(1, descriptor, 0x40044101u, bind, sizeof bind, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, descriptor, 0x40044101u, bind, sizeof bind, NULL, 0) == 8);
    CHECK(d3_nv_close(1, descriptor) == 8);
    uint32_t fifo[8] = {1024, 1};
    CHECK(d3_nv_ioctl(1, channel, 0xc020481au, fifo, sizeof fifo, NULL, 0) == 0);
    CHECK(fifo[3] != 0 && fifo[4] == 0);
    CHECK(d3_nv_ioctl(1, channel, 0xc020481au, fifo, sizeof fifo, NULL, 0) == 13);
    uint32_t context[4] = {0xb197};
    CHECK(d3_nv_ioctl(1, channel, 0xc0104809u, context, sizeof context, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, channel, 0xc0104809u, context, sizeof context, NULL, 0) == 13);
    context[0] = 0xdead;
    CHECK(d3_nv_ioctl(1, channel, 0xc0104809u, context, sizeof context, NULL, 0) == 4);
    uint32_t timeslice[1] = {999};
    CHECK(d3_nv_ioctl(1, channel, 0x4004481du, timeslice, sizeof timeslice, NULL, 0) == 4);
    timeslice[0] = 2000;
    CHECK(d3_nv_ioctl(1, channel, 0x4004481du, timeslice, sizeof timeslice, NULL, 0) == 0);
    CHECK(d3_nv_ioctl(1, channel, 0xc004481du, timeslice, sizeof timeslice, NULL, 0) == 0);
    uint32_t client_data[2] = {0x12345678, 0x98765432};
    CHECK(d3_nv_ioctl(1, channel, 0x40084714u, client_data, sizeof client_data, NULL, 0) == 0);
    memset(client_data, 0, sizeof client_data);
    CHECK(d3_nv_ioctl(1, channel, 0x80084715u, client_data, sizeof client_data, NULL, 0) == 0);
    CHECK(client_data[0] == 0x12345678 && client_data[1] == 0x98765432);
    uint32_t map_descriptor;
    CHECK(d3_nv_open(1, "/dev/nvmap", &map_descriptor) == 0);
    void *notifier_buffer = aligned_alloc(4096, 4096);
    CHECK(notifier_buffer != NULL);
    memset(notifier_buffer, 0xff, 4096);
    uint32_t notifier_create[2] = {4096};
    CHECK(d3_nv_ioctl(1, map_descriptor, 0xc0080101u, notifier_create, sizeof notifier_create, NULL, 0) == 0);
    uint32_t notifier_allocate[8] = {notifier_create[1], 0, 0, 4096};
    const uint64_t notifier_address = (uint64_t)(uintptr_t)notifier_buffer;
    memcpy(notifier_allocate + 6, &notifier_address, 8);
    CHECK(d3_nv_ioctl(1, map_descriptor, 0xc0200104u, notifier_allocate, sizeof notifier_allocate, NULL, 0) == 0);
    uint32_t notifier[6] = {4088, 0, 16, 0, notifier_create[1]};
    CHECK(d3_nv_ioctl(1, channel, 0xc018480cu, notifier, sizeof notifier, NULL, 0) == 11);
    notifier[0] = 32;
    CHECK(d3_nv_ioctl(1, channel, 0xc018480cu, notifier, sizeof notifier, NULL, 0) == 0);
    const unsigned char *notifier_bytes = notifier_buffer;
    CHECK(notifier_bytes[31] == 0xff && notifier_bytes[32] == 0 && notifier_bytes[47] == 0 && notifier_bytes[48] == 0xff);
    uint32_t notifier_release[6] = {notifier_create[1]};
    CHECK(d3_nv_ioctl(1, map_descriptor, 0xc0180105u, notifier_release, sizeof notifier_release, NULL, 0) == 0);
    CHECK(d3_nv_close(1, channel) == 0);
    uint32_t notifier_query[3] = {notifier_create[1], 1};
    CHECK(d3_nv_ioctl(1, map_descriptor, 0xc00c0109u, notifier_query, sizeof notifier_query, NULL, 0) == 11);
    CHECK(d3_nv_close(1, map_descriptor) == 0);
    free(notifier_buffer);
    CHECK(d3_nv_close(1, descriptor) == 0);
    puts("PASS: GPU characteristics, nvmap lifecycle, per-session descriptors and VA reservations");
    return 0;
}
