/* Exercises the production registry lookup, guards and guest-call bridge with
   synthetic widgets; no game process, save data or APK installation needed. */
#include "../host/d3_host.c"
#include <assert.h>
#include <math.h>

typedef struct { uint64_t next, key, object; } TestNode;
typedef union { uint64_t align; unsigned char bytes[0x200]; } TestObject;

static int g_translations;
static uint64_t g_expected_guest_tp, g_expected_guest_x18;
static int g_wrong_guest_context;
extern void d3_test_hud_frame_resume(void);
extern void d3_test_invoke_hud_frame(uint64_t, uint64_t, uint64_t *);
static void test_translate(uint64_t object, const float delta[2]) {
    uint64_t tp, x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    __asm__ volatile("mov %0, x18" : "=r"(x18));
    if (tp != g_expected_guest_tp || x18 != g_expected_guest_x18) g_wrong_guest_context = 1;
    D3HudRect *rect = (D3HudRect *)(uintptr_t)(object + 0x88);
    rect->left += delta[0]; rect->right += delta[0];
    rect->top += delta[1]; rect->bottom += delta[1];
    g_translations++;
}

static unsigned bucket(uint64_t key) {
    uint32_t hash = 2166136261u;
    for (unsigned i = 0; i < 4; i++) { hash ^= (uint8_t)(key >> (8 * i)); hash *= 16777619u; }
    return hash & 15u;
}

static void init_object(TestObject *obj, uint64_t key, uint64_t parent, D3HudRect rect) {
    uint64_t *words = (uint64_t *)obj->bytes;
    memset(obj, 0, sizeof *obj);
    words[0] = g_bias + 0x20aa208u;
    words[3] = 4;
    words[6] = key;
    words[7] = parent;
    memcpy(obj->bytes + 0x88, &rect, sizeof rect);
}

static void add_node(TestNode *node, uint64_t buckets[16], uint64_t key, TestObject *obj) {
    unsigned index = bucket(key);
    *node = (TestNode){buckets[index], key, (uint64_t)(uintptr_t)obj};
    buckets[index] = (uint64_t)(uintptr_t)node;
}

static void tick(uint64_t tp, uint64_t x18) {
    usleep(120000);
    d3_hud_update(tp, x18);
}

int main(void) {
    const size_t image_size = 0x2150000;
    void *image = mmap(NULL, image_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(image != MAP_FAILED);
    g_bias = (uint64_t)(uintptr_t)image;
    uint32_t *call_site = (uint32_t *)(uintptr_t)(g_bias + 0x13b2fc0u);
    call_site[0] = 0x58000050u; call_site[1] = 0xd61f0200u;
    uint64_t target = (uint64_t)(uintptr_t)test_translate;
    memcpy(call_site + 2, &target, sizeof target);
    __builtin___clear_cache((char *)call_site, (char *)call_site + 16);
    long page_size = sysconf(_SC_PAGESIZE);
    assert(page_size > 0);
    uintptr_t page = (uintptr_t)call_site & ~((uintptr_t)page_size - 1);
    assert(mprotect((void *)page, (size_t)page_size, PROT_READ | PROT_EXEC) == 0);

    uint64_t root[3] = {0}, world[0x172] = {0}, manager[1] = {0};
    struct { uint32_t mask, count; uint64_t reserved, buckets; } map = {15, 4, 0, 0};
    uint64_t buckets[16] = {0};
    TestNode nodes[4];
    TestObject objs[4];
    const D3HudRect root_rect = {-160, 0, 1120.5f, 720.5f};
    init_object(&objs[0], D3_HUD_MAP_PARENT_KEY, 1, root_rect);
    init_object(&objs[1], D3_HUD_MAP_KEY, D3_HUD_MAP_PARENT_KEY, (D3HudRect){895.6f,472.4f,896.6f,473.4f});
    init_object(&objs[2], D3_HUD_PLAYER_KEY, UINT64_C(4801268128208691105), root_rect);
    init_object(&objs[3], D3_HUD_GROUP_KEY, D3_HUD_PLAYER_KEY, (D3HudRect){-115.6f,552.4f,217.4f,696.4f});
    add_node(&nodes[0], buckets, D3_HUD_MAP_PARENT_KEY, &objs[0]);
    add_node(&nodes[1], buckets, D3_HUD_MAP_KEY, &objs[1]);
    add_node(&nodes[2], buckets, D3_HUD_PLAYER_KEY, &objs[2]);
    add_node(&nodes[3], buckets, D3_HUD_GROUP_KEY, &objs[3]);
    map.buckets = (uint64_t)(uintptr_t)buckets;
    manager[0] = (uint64_t)(uintptr_t)&map;
    world[0xb80 / 8] = (uint64_t)(uintptr_t)manager;
    root[2] = (uint64_t)(uintptr_t)world;
    *(uint64_t *)(uintptr_t)(g_bias + 0x214a840u) = (uint64_t)(uintptr_t)root;
    uint64_t tp, x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    __asm__ volatile("mov %0, x18" : "=r"(x18));
    g_expected_guest_tp = tp; g_expected_guest_x18 = x18;
    tick(tp, x18);
    D3HudRect *anchor = (D3HudRect *)(objs[1].bytes + 0x88);
    D3HudRect *hud = (D3HudRect *)(objs[3].bytes + 0x88);
    assert(g_translations == 2);
    assert(fabsf(anchor->left + 138.4f) < 0.01f && fabsf(anchor->top + 1.6f) < 0.01f);
    assert(fabsf((hud->left + hud->right) - (root_rect.left + root_rect.right)) < 0.01f);
    tick(tp, x18);
    assert(g_translations == 2);
    ((uint64_t *)objs[3].bytes)[7] = 0;
    anchor->left += 20; anchor->right += 20;
    tick(tp, x18);
    assert(g_translations == 2); /* invalid parent must not partially modify the scene */
    ((uint64_t *)objs[3].bytes)[7] = D3_HUD_PLAYER_KEY;
    tick(tp, x18);
    assert(g_translations == 3);
    map.mask = 0xfffffffeu;
    anchor->left += 20; anchor->right += 20;
    tick(tp, x18);
    assert(g_translations == 3);
    map.mask = 15;
    thread_region_set_host_tp(tp);
    g_expected_guest_tp = this_guest_tls();
    g_expected_guest_x18 = UINT64_C(0x123400005678);
    g_hud_frame_resume = (uint64_t)(uintptr_t)d3_test_hud_frame_resume;
    uint64_t observed[4] = {0};
    usleep(120000);
    d3_test_invoke_hud_frame(g_expected_guest_tp, g_expected_guest_x18, observed);
    assert(g_translations == 4 && !g_wrong_guest_context);
    assert(observed[0] == 0x1234 && observed[1] == 0x5678);
    assert(observed[2] == g_expected_guest_tp && observed[3] == g_expected_guest_x18);
    uint64_t after_tp, after_x18;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(after_tp));
    __asm__ volatile("mov %0, x18" : "=r"(after_x18));
    assert(after_tp == tp && after_x18 == x18);
    puts("HUD registry, layout, invalid-state guards and guest frame/TLS bridges: PASS");
    return 0;
}
