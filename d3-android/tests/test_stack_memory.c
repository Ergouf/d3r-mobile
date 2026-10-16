/* Android-native regression test: exercise private memory helpers without a guest. */
#include "../host/d3_host.c"

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static MemInfo inspect_memory(uint64_t address) {
    MemInfo memory = {0};
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)&memory;
    saved.x[2] = address;
    query_memory(&saved);
    return memory;
}

int main(void) {
    g_os_page = (size_t)sysconf(_SC_PAGESIZE);
    CHECK(g_os_page == 0x1000);
    g_heap_cap = 0x10000;
    g_heap_cur = g_heap_cap;
    g_heap = (uint64_t)(uintptr_t)map_pages(g_heap_cap, PROT_READ | PROT_WRITE);
    g_stack_region = (uint64_t)(uintptr_t)map_pages(STACK_REGION_SIZE, PROT_NONE);
    g_stack = g_stack_region + STACK_REGION_SIZE - STACK_SIZE;
    g_guard = g_stack - GUARD_SIZE;
    add_fixed(g_stack, STACK_SIZE, MEM_STACK, PERM_RW);
    add_fixed(g_guard, GUARD_SIZE, MEM_INACCESSIBLE, 0);
    compose_regions();

    d3_saved saved = {0};
    saved.x[1] = I_STACK_ADDR;
    get_info(&saved);
    CHECK(saved.x[0] == 0 && saved.x[1] == g_stack_region);
    saved.x[1] = I_STACK_SIZE;
    get_info(&saved);
    CHECK(saved.x[0] == 0 && saved.x[1] == STACK_REGION_SIZE);
    CHECK(g_stack_region != g_stack);

    const uint64_t source = g_heap + 0x4000;
    const uint64_t destination = g_stack_region + 0x8000;
    const uint64_t size = 0x2000;
    unsigned char *input = (unsigned char *)(uintptr_t)source;
    unsigned char *output = (unsigned char *)(uintptr_t)destination;
    for (size_t index = 0; index < size; index++)
        input[index] = (unsigned char)(index * 7u);

    CHECK(inspect_memory(destination).state == MEM_FREE);
    CHECK(stack_map_memory(destination + 1, source, size, 1) != 0);
    CHECK(stack_map_memory(destination, source + 1, size, 1) != 0);
    CHECK(stack_map_memory(destination, source, 0, 1) != 0);
    CHECK(stack_map_memory(g_stack_region - 0x1000, source, size, 1) != 0);
    CHECK(stack_map_memory(g_stack, source, size, 1) != 0);
    CHECK(stack_map_memory(destination, UINT64_MAX - 0xfff, size, 1) != 0);
    CHECK(stack_map_memory(destination, source, size, 0) != 0);

    CHECK(stack_map_memory(destination, source, size, 1) == 0);
    for (size_t index = 0; index < size; index++)
        CHECK(output[index] == (unsigned char)(index * 7u));
    unsigned char byte;
    CHECK(!safe_read(source, &byte, 1));
    MemInfo locked = inspect_memory(source);
    CHECK(locked.state == MEM_NORMAL && locked.perm == 0 && (locked.attr & 1u));
    MemInfo stack = inspect_memory(destination);
    CHECK(stack.addr == destination && stack.size == size);
    CHECK(stack.state == MEM_STACK && stack.perm == PERM_RW);
    MemInfo gap = inspect_memory(destination - 0x1000);
    CHECK(gap.state == MEM_FREE && gap.addr + gap.size <= destination);
    CHECK(stack_map_memory(destination + 0x1000, g_heap, size, 1) != 0);
    CHECK(stack_map_memory(destination + 0x4000, source, size, 1) != 0);
    CHECK(stack_map_memory(destination, source, size + 0x1000, 0) != 0);

    output[0] = 0x5a;
    output[size - 1] = 0xa5;
    CHECK(stack_map_memory(destination, source, size, 0) == 0);
    CHECK(input[0] == 0x5a && input[size - 1] == 0xa5);
    CHECK(!safe_read(destination, &byte, 1));
    MemInfo restored = inspect_memory(source);
    CHECK(restored.state == MEM_NORMAL && restored.perm == PERM_RW && restored.attr == 0);
    CHECK(inspect_memory(destination).state == MEM_FREE);
    CHECK(stack_map_memory(destination, source, size, 0) != 0);

    for (int round = 0; round < 32; round++) {
        CHECK(stack_map_memory(destination, source, size, 1) == 0);
        output[0] = (unsigned char)round;
        CHECK(stack_map_memory(destination, source, size, 0) == 0);
        CHECK(input[0] == (unsigned char)round);
    }
    CHECK(munmap((void *)(uintptr_t)g_heap, g_heap_cap) == 0);
    CHECK(munmap((void *)(uintptr_t)g_stack_region, STACK_REGION_SIZE) == 0);
    puts("PASS: stack region, MapMemory/UnmapMemory backing, protections, queries, and rejection cases");
    return 0;
}
