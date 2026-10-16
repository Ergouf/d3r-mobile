/* Android-native bootstrap regression with synthetic guest entry points. */
#include "../host/d3_host.c"

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static unsigned sdk_init_calls;
static unsigned main_init_calls;
static unsigned sdk_ctor_calls;
static unsigned main_ctor_calls;
static unsigned main_calls;
static unsigned order_errors;

static void sdk_constructor(void) {
    sdk_ctor_calls++;
}

static void main_constructor(void) {
    main_ctor_calls++;
}

static void synthetic_init(uint64_t preferred, uint64_t bytes) {
    const uint64_t *array = (const uint64_t *)(uintptr_t)(g_bias + preferred);
    for (uint64_t i = 0; i < bytes / sizeof(*array); i++)
        ((void (*)(void))(uintptr_t)array[i])();
}

static void sdk_init(void) {
    sdk_init_calls++;
    synthetic_init(D3_SDK_INIT_ARRAY, D3_SDK_INIT_ARRAYSZ);
}

static void main_init(void) {
    if (sdk_ctor_calls != D3_SDK_INIT_ARRAYSZ / 8)
        order_errors++;
    main_init_calls++;
    synthetic_init(D3_MAIN_INIT_ARRAY, D3_MAIN_INIT_ARRAYSZ);
}

static void synthetic_main(void) {
    main_calls++;
    if (sdk_ctor_calls != D3_SDK_INIT_ARRAYSZ / 8 ||
        main_ctor_calls != D3_MAIN_INIT_ARRAYSZ / 8)
        order_errors++;
}

static void emit_jump(uint64_t preferred, void (*target)(void)) {
    uint32_t *code = (uint32_t *)(uintptr_t)(g_bias + preferred);
    const uint64_t address = (uint64_t)(uintptr_t)target;
    code[0] = 0x58000050u;
    code[1] = 0xd61f0200u;
    memcpy(code + 2, &address, sizeof address);
}

int main(void) {
    g_os_page = (size_t)sysconf(_SC_PAGESIZE);
    const size_t size = (size_t)align_up_guest(
        D3_MAIN_INIT_ARRAY + D3_MAIN_INIT_ARRAYSZ, g_os_page);
    void *image = mmap(NULL, size, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    CHECK(image != MAP_FAILED);
    g_bias = (uint64_t)(uintptr_t)image;
    uint64_t table[5] = {0};
    g_table = table;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(g_host_tp));
    __asm__ volatile("mov %0, x18" : "=r"(g_host_x18));
    g_guest_tp = g_host_tp;
    g_guest_x18 = g_host_x18;

    const uint64_t returns[] = {
        D3_SYM__init_libc0, D3_SYM_nnosInitialize, D3_SYM__init_libc1,
        D3_SYM_nninitInitializeSdkModule, D3_SYM_nninitStartup,
        D3_SYM__init_libc2, D3_SYM_SetHostArgc, D3_SYM_SetHostArgv
    };
    for (size_t i = 0; i < sizeof returns / sizeof returns[0]; i++)
        *(uint32_t *)(uintptr_t)(g_bias + returns[i]) = 0xd65f03c0u;
    const uint64_t sdk_ctor = D3_SDK_BASE + 0x1000;
    const uint64_t main_ctor = D3_MAIN_BASE + 0x1000;
    emit_jump(D3_SDK_DT_INIT, sdk_init);
    emit_jump(D3_MAIN_DT_INIT, main_init);
    emit_jump(sdk_ctor, sdk_constructor);
    emit_jump(main_ctor, main_constructor);
    emit_jump(D3_SYM_nnMain, synthetic_main);
    uint64_t *sdk_array = (uint64_t *)(uintptr_t)(g_bias + D3_SDK_INIT_ARRAY);
    uint64_t *main_array = (uint64_t *)(uintptr_t)(g_bias + D3_MAIN_INIT_ARRAY);
    for (size_t i = 0; i < D3_SDK_INIT_ARRAYSZ / 8; i++)
        sdk_array[i] = g_bias + sdk_ctor;
    for (size_t i = 0; i < D3_MAIN_INIT_ARRAYSZ / 8; i++)
        main_array[i] = g_bias + main_ctor;
    __builtin___clear_cache((char *)image, (char *)image + size);
    CHECK(mprotect(image, size, PROT_READ | PROT_EXEC) == 0);
    g_reg[0] = (Region){g_bias, size, MEM_CODE, PERM_R | PERM_X};
    g_nreg = 1;

    boot_sequence();
    CHECK(sdk_init_calls == 1 && main_init_calls == 1);
    CHECK(sdk_ctor_calls == D3_SDK_INIT_ARRAYSZ / 8);
    CHECK(main_ctor_calls == D3_MAIN_INIT_ARRAYSZ / 8);
    CHECK(main_calls == 1 && order_errors == 0);
    CHECK(g_guest_tp == g_host_tp && g_guest_x18 == g_host_x18);
    CHECK(munmap(image, size) == 0);
    puts("PASS: DT_INIT owns SDK/main constructors once; nnMain follows both modules");
    return 0;
}
