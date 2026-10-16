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

/* Constraint: on_tpidrro writes only the requested register (never blindly to
   LR), so all other registers/NZCV/q survive and only x16/x17 spill into pair. */
static int run_tpidrro_regression(void) {
    static const uint64_t lr_sentinel = UINT64_C(0x0000deadbeef0000);
    static const uint64_t nzcv_sentinel = UINT64_C(0xa0000000);
    const uint64_t tlr = UINT64_C(0x77aa0000cafe);
    const uint32_t targets[] = {0u, 8u, 16u, 17u, 30u};

    uint64_t table[5] = {0};
    table[D3_HOST_OFF_TLR / 8] = tlr;
    uint64_t *const saved_table = g_table;

    struct { d3_saved saved; uint64_t pair[2]; } frame;
    CHECK(sizeof(d3_saved) == 0x180u);
    CHECK((const unsigned char *)&frame.pair[0] - (const unsigned char *)&frame.saved
          == (long)sizeof(d3_saved));

    for (size_t t = 0; t < sizeof targets / sizeof targets[0]; t++) {
        const uint32_t dest = targets[t];
        memset(&frame, 0, sizeof frame);
        for (int r = 0; r < 31; r++)
            frame.saved.x[r] = 0x1000u + (uint64_t)r;
        frame.saved.x[30] = lr_sentinel;
        frame.saved.nzcv = nzcv_sentinel;
        for (int i = 0; i < 8; i++)
            for (int j = 0; j < 16; j++)
                frame.saved.q[i][j] = (unsigned char)(i * 16 + j);

        g_table = table;
        on_tpidrro(&frame.saved, dest);
        g_table = saved_table; /* restore before any CHECK can early-return */

        CHECK(frame.saved.x[dest] == tlr); /* destination holds exactly TLR */
        for (int r = 0; r < 31; r++) {
            if ((uint32_t)r == dest)
                continue;
            const uint64_t expected = (r == 30) ? lr_sentinel : 0x1000u + (uint64_t)r;
            CHECK(frame.saved.x[r] == expected);
        }
        CHECK(frame.saved.nzcv == nzcv_sentinel);
        for (int i = 0; i < 8; i++)
            for (int j = 0; j < 16; j++)
                CHECK(frame.saved.q[i][j] == (unsigned char)(i * 16 + j));
        CHECK(frame.pair[0] == (dest == 16 ? tlr : 0));
        CHECK(frame.pair[1] == (dest == 17 ? tlr : 0));
    }
    CHECK(g_table == saved_table);
    return 0;
}

static int run_memory_dump_regression(void) {
    unsigned char *pages = mmap(NULL, g_os_page * 2, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(pages != MAP_FAILED);
    uint64_t *root = (uint64_t *)(void *)pages;
    uint64_t *child = (uint64_t *)(void *)(pages + 0x200);
    root[0] = (uint64_t)(uintptr_t)child;
    root[16] = UINT64_C(0x1122334455667788);
    child[16] = UINT64_C(0x8877665544332211);
    child[0] = 0;
    CHECK(mprotect(pages + g_os_page, g_os_page, PROT_NONE) == 0);
    CHECK(mprotect(pages, g_os_page, PROT_READ) == 0);

    g_dump_used = 0;
    dump_memory_links(21, (uint64_t)(uintptr_t)root);
    CHECK(g_dump_used < sizeof g_dump);
    g_dump[g_dump_used] = 0;
    CHECK(strstr(g_dump, "m_register=0000000000000015\n") != NULL);
    CHECK(strstr(g_dump, "m_depth=0000000000000001\n") != NULL);
    CHECK(strstr(g_dump, "m16=1122334455667788\n") != NULL);
    CHECK(strstr(g_dump, "m16=8877665544332211\n") != NULL);
    CHECK(strstr(g_dump, "m_unreadable") == NULL);

    const uint64_t invalid[] = {0, UINT64_MAX,
        (uint64_t)(uintptr_t)(pages + g_os_page),
        (uint64_t)(uintptr_t)(pages + g_os_page - 64)};
    for (size_t i = 0; i < sizeof invalid / sizeof invalid[0]; i++) {
        g_dump_used = 0;
        dump_memory_links(21, invalid[i]);
        CHECK(g_dump_used < sizeof g_dump);
        g_dump[g_dump_used] = 0;
        CHECK(strstr(g_dump, "m_unreadable\n") != NULL);
        CHECK(strstr(g_dump, "m0=") == NULL);
    }
    g_dump_used = 0;
    dump_memory_links(19, (uint64_t)(uintptr_t)child);
    CHECK(g_dump_used < sizeof g_dump);
    g_dump[g_dump_used] = 0;
    CHECK(strstr(g_dump, "m_depth=0000000000000001\n") != NULL);
    CHECK(strstr(g_dump, "m_unreadable\n") != NULL);
    CHECK(munmap(pages, g_os_page * 2) == 0);
    g_dump_used = 0;
    return 0;
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
    CHECK(run_tpidrro_regression() == 0);
    CHECK(run_memory_dump_regression() == 0);
    CHECK(munmap((void *)(uintptr_t)g_heap, g_heap_cap) == 0);
    CHECK(munmap((void *)(uintptr_t)g_stack_region, STACK_REGION_SIZE) == 0);
    puts("PASS: stack region, MapMemory/UnmapMemory backing, protections, queries, rejection cases, tpidrro TLR, bounded crash memory");
    return 0;
}
