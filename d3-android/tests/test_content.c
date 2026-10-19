#define D3_CONTENT_ROOT D3_DATA_ROOT "/content-fixture"
#include "../host/d3_host.c"
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)
int main(void) {
    mkdir(D3_DATA_ROOT, 0700);
    mkdir(D3_CONTENT_ROOT, 0700);
    mkdir(D3_CONTENT_ROOT "/AddOnContent", 0700);
    mkdir(D3_CONTENT_ROOT "/AddOnContent/11", 0700);
    uint64_t cache_size = 0;
    const char name[] = "voice";
    unsigned char cache[4096];
    CHECK(hook_fs_addon_cache_size((uint64_t)(uintptr_t)&cache_size, 11) != 0);
    FILE *file = fopen(D3_CONTENT_ROOT "/AddOnContent/11/.d3-content-complete", "we");
    CHECK(file && fputs("01001b300b9bf00b\n", file) >= 0 && fclose(file) == 0);
    file = fopen(D3_CONTENT_ROOT "/AddOnContent/11/ztCN_Act1.cpk", "we");
    CHECK(file && fputs("CPK test voice", file) >= 0 && fclose(file) == 0);
    CHECK(hook_fs_addon_cache_size((uint64_t)(uintptr_t)&cache_size, 11) == 0 && cache_size == 4096);
    CHECK(hook_fs_mount_addon((uint64_t)(uintptr_t)name, 11, (uint64_t)(uintptr_t)cache, sizeof cache) == 0);
    CHECK(hook_fs_mount_addon((uint64_t)(uintptr_t)"missing", 12, (uint64_t)(uintptr_t)cache, sizeof cache) != 0);
    char host[512];
    CHECK(guest_data_host("voice:/ztCN_Act1.cpk", host, sizeof host, 0) == 0);
    CHECK(!strcmp(host, D3_CONTENT_ROOT "/AddOnContent/11/ztCN_Act1.cpk"));
    const int handle = fs_open_host_mode("voice:/ztCN_Act1.cpk", 0);
    char data[32] = {0};
    CHECK(handle > 0 && fs_read(handle, 0, (uint64_t)(uintptr_t)data, 14) == 14);
    CHECK(!memcmp(data, "CPK test voice", 14) && hook_fs_close_file(handle) == 0);
    CHECK(guest_data_host("voice:/../secret", host, sizeof host, 0) != 0);
    CHECK(guest_data_host("voice:/ztCN_Act1.cpk", host, sizeof host, 1) != 0);
    CHECK(hook_fs_unmount((uint64_t)(uintptr_t)name) == 0);
    CHECK(guest_data_host("voice:/ztCN_Act1.cpk", host, sizeof host, 0) != 0);
    CHECK(unlink(D3_CONTENT_ROOT "/AddOnContent/11/ztCN_Act1.cpk") == 0);
    CHECK(unlink(D3_CONTENT_ROOT "/AddOnContent/11/.d3-content-complete") == 0);
    CHECK(rmdir(D3_CONTENT_ROOT "/AddOnContent/11") == 0);
    CHECK(rmdir(D3_CONTENT_ROOT "/AddOnContent") == 0 && rmdir(D3_CONTENT_ROOT) == 0);
    puts("PASS: installed content, real addon mount/path/read, missing content and read-only traversal rejection");
    return 0;
}
