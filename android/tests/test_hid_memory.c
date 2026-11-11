#include "../host/d3_host.c"

static int safe_write(uint64_t address, const void *source, uint64_t size) {
    struct iovec local = {(void *)source, (size_t)size};
    struct iovec remote = {(void *)(uintptr_t)address, (size_t)size};
    return syscall(SYS_process_vm_writev, getpid(), &local, 1, &remote, 1, 0) == (ssize_t)size;
}

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static int mapping_case(uint64_t permission) {
    const size_t size = 0x40000u;
    const int fixed_count = g_nfixed;
    const int shared_count = g_nshared;
    void *reservation = mmap(NULL, size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(reservation != MAP_FAILED);
    const uint64_t address = (uint64_t)(uintptr_t)reservation;
    CHECK(map_shared_at(address, size, permission) == address);
    uint32_t style = 0;
    CHECK(safe_read(address + 0x9a00u, &style, sizeof style));
    CHECK(style == 1 && (style & (style - 1)) == 0);
    uint32_t handheld_style = UINT32_MAX;
    CHECK(safe_read(address + 0x9a00u + 8u * 0x5000u, &handheld_style, sizeof handheld_style));
    CHECK(handheld_style == 0);
    uint64_t handheld_count = UINT64_MAX;
    CHECK(safe_read(address + 0x9a00u + 0x378u + 0x18u, &handheld_count, sizeof handheld_count));
    CHECK(handheld_count == 0);
    CHECK(safe_write(address + 0x9a00u, &style, sizeof style) == (permission == 3));
    MemInfo memory = {0};
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)&memory;
    saved.x[2] = address;
    query_memory(&saved);
    CHECK(memory.perm == permission);
    for (unsigned index = 0; index < 48; index++) {
        d3_hid_update((1u << 0) | (1u << 9), 40000, -40000, -32767, 32767);
        uint64_t header[4], entry[6];
        CHECK(safe_read(address + 0x9a28u, header, sizeof header));
        CHECK(header[2] < 17 && header[3] <= 17);
        CHECK(safe_read(address + 0x9a48u + header[2] * 0x30u, entry, sizeof entry));
        CHECK(entry[0] == entry[1] && entry[0] > 1);
        CHECK((entry[2] & ((1u << 0) | (1u << 9))) == ((1u << 0) | (1u << 9)));
        CHECK((entry[2] & ((1u << 18) | (1u << 19) | (1u << 20) | (1u << 21))) != 0);
        int32_t axes[4]; memcpy(axes, &entry[3], sizeof axes);
        CHECK(axes[0] == 32767 && axes[1] == -32767 && axes[2] == -32767 && axes[3] == 32767);
        CHECK((entry[5] & 3) == 3);
    }
    d3_hid_update(0, 0, 0, 0, 0);
    uint64_t header[4], entry[6];
    CHECK(safe_read(address + 0x9a28u, header, sizeof header));
    CHECK(safe_read(address + 0x9a48u + header[2] * 0x30u, entry, sizeof entry));
    CHECK(entry[2] == 0 && entry[3] == 0 && entry[4] == 0);
    d3_hid_unmap(address);
    CHECK(munmap(reservation, size) == 0);
    d3_hid_update(0xffff, 1, 2, 3, 4); /* Detached mappings cannot be written. */
    g_nfixed = fixed_count;
    g_nshared = shared_count;
    compose_regions();
    return 0;
}

int main(void) {
    g_os_page = (size_t)sysconf(_SC_PAGESIZE);
    CHECK(mapping_case(1) == 0);
    CHECK(mapping_case(3) == 0);
    puts("PASS: read-only/RW HID views, writable alias, ring wrap, simultaneous buttons, clamped axes, release and detach");
    return 0;
}
