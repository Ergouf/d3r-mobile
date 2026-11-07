"""Run the production native Space close path against bounded memory and call stubs.

Offline regression for native_ui_close_request/ui_close_page_allowed/ui_close_target/
ui_close_tick: which native close (service navigation, NPC cancel, prompt cancel) a
Space request may invoke, and when a stale or foreign request must be refused.
Live UI content is verified separately through SDL input.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference/ScarletNX-src/src/nx/runtime/native_world.c"
OUT = ROOT / "out/windows/kbm/session/ui-close-tests"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_hover_wheel import function  # the hover suite owns the source slicer

NAMES = ["native_world_cancel", "native_ui_close_request", "ui_path_key",
         "ui_close_page_allowed", "ui_close_target", "ui_close_tick"]

PRELUDE = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { u64 x[31], pc; } CPU;
typedef struct { u64 x0; float f0; } GuestResult;
typedef struct { const CPU* cpu; u64 map; float point[2]; int hover; } UiPick;
typedef int PMutex;
static PMutex g_pointer_lock;
/* Close-path queues owned by the real native_world.c. */
static int g_cancel, g_have_pointer, g_have_hover, g_world_command, g_item_drag_active;
static unsigned g_ui_read, g_ui_count, g_skill_read, g_skill_count;
static u32 g_frames;
/* Bounded guest memory: covers the 0x97F3840 NPC token and the UI registry. */
static unsigned char memory[0x9900000];
/* Registry stub: name key -> object slot, plus the parent chain and view flags. */
static u64 keys[128], parents[128];
static unsigned g_slots;
static int log_calls;
#define GP(a) (memory + (a))
#define LOG(...) do { log_calls++; if (0) printf(__VA_ARGS__); } while (0)
static void pm_lock(PMutex* p) { (void)p; }
static void pm_unlock(PMutex* p) { (void)p; }
static int readable(u64 a, size_t n) { return a && a < sizeof memory && n <= sizeof memory - a; }
static int read32(u64 a, u32* v) { if (!readable(a, 4)) return 0; memcpy(v, GP(a), 4); return 1; }
static int read64(u64 a, u64* v) { if (!readable(a, 8)) return 0; memcpy(v, GP(a), 8); return 1; }
static void w32(u64 a, u32 v) { memcpy(GP(a), &v, 4); }
static void w64(u64 a, u64 v) { memcpy(GP(a), &v, 8); }
static u64 ui_object(u64 m, u64 key) {
    (void)m;
    if (key == UINT64_MAX) return 0;
    for (unsigned i = 1; i < 128; i++) if (keys[i] == key) return (u64)i * 0x1000;
    return 0;
}
static u64 ui_parent(u64 m, u64 obj) {
    (void)m;
    return obj && obj < 0x80000 ? parents[obj / 0x1000] : 0;
}
static int ui_visible(u64 m, u64 obj) {
    (void)m;
    for (int i = 0; obj && i < 64; i++, obj = parents[obj / 0x1000]) {
        u32 flags;
        if (obj >= 0x80000 || !read32(obj + 0x18, &flags) || !(flags & 4)) return 0;
        if (!parents[obj / 0x1000]) return 1;
    }
    return 0;
}
static int ui_within(u64 m, u64 obj, u64 ancestor) {
    (void)m;
    for (int i = 0; obj && obj < 0x80000 && i < 64; i++, obj = parents[obj / 0x1000])
        if (obj == ancestor) return 1;
    return 0;
}
static int ui_code(u64 pc) { return pc >= 0x8005000 && pc < 0x8c78000 && !(pc & 3); }
"""

STUBS = r"""
/* Only the focus getter and the three observed close entries may be called;
   the prompt accept callback 0x816AAB0 must never run from a close. */
static u64 g_focus_key = UINT64_MAX;
static int g_focus_ok = 1, g_close_ok = 1;
static int callback_calls, accept_calls, foreign_calls, got_pc;
static unsigned got_argc;
static u64 got_arg0, got_arg1;
static int guest_call(const CPU* cpu, u64 pc, const u64* args, unsigned count,
                      const float* fargs, unsigned fcount, GuestResult* result) {
    (void)cpu; (void)fargs; (void)fcount;
    if (pc == 0x832D180) {
        w64(0x73000, g_focus_key);
        if (result) result->x0 = 0x73000;
        return g_focus_ok;
    }
    if (pc == 0x816BB90 || pc == 0x820EF90 || pc == 0x816A9C0) {
        callback_calls++; got_pc = (int)pc; got_argc = count;
        got_arg0 = count ? args[0] : 0;
        got_arg1 = count > 1 ? args[1] : 0;
        return g_close_ok;
    }
    if (pc == 0x816AAB0) { accept_calls++; return 1; }
    foreign_calls++;
    return 0;
}
/* ui_service_state/ui_wheel_allowed have their own coverage in test_hover_wheel;
   here they are the two service gates the close path consults. */
static int g_service, g_wheel;
static u64 g_service_page, g_service_controller;
static u32 g_service_current;
static const UiServiceSpec g_fake_service = {"vendor", 2, 4, 0, 0, {0}, {0}, {0}, {0}, {0}, {0}};
static int ui_service_state(u64 map, UiServiceState* state) {
    (void)map;
    if (!g_service) return 0;
    state->spec = &g_fake_service;
    state->controller = g_service_controller;
    state->page = g_service_page;
    state->current = g_service_current;
    state->mode = 0;
    return 1;
}
static int ui_wheel_allowed(UiPick* pick, u64 manager) {
    (void)pick; (void)manager;
    return g_wheel;
}
"""
CASES = r"""
static CPU cpu;
static const u64 g_map = 0x100000, g_manager = 0x200000;
static u64 g_normal, g_page, g_focus, g_owner, g_options, g_dialog;
static u64 g_vt = 0x800000, g_table = 0x850000;
static int failures, checks;
#define CHECK(name, condition) do { checks++; if (!(condition)) { printf("FAIL %s\n", name); failures++; } } while (0)
#define TICK() ui_close_tick(&cpu, g_map, g_manager)
#define SPACE() native_ui_close_request()
static u64 mk(u64 key, u64 parent, int visible) {
    unsigned slot = g_slots++;
    u64 obj;
    if (slot >= 128) return 0;
    obj = (u64)slot * 0x1000;
    keys[slot] = key;
    parents[slot] = parent;
    w32(obj + 0x18, visible ? 4u : 0u);
    return obj;
}
/* Webview-style subscriber: vtable+0xB0 method plus a callback table entry. */
static void mk_cb(u64 obj, u64 callback) {
    u64 vt = (g_vt += 0x100), table = (g_table += 0x100);
    w64(obj, vt);
    w64(vt + 0xB0, 0x83B81F0);
    w64(obj + 0x118, table);
    w64(table + 0x20, callback);
}
static void sub(u64 obj) {
    u32 count;
    read32(0x210008, &count);
    w64(0x220000 + (u64)count * 8, obj);
    w32(0x210008, count + 1);
}
static void base(void) {
    memset(memory, 0, sizeof memory);
    memset(keys, 0, sizeof keys);
    memset(parents, 0, sizeof parents);
    g_slots = 2;
    keys[1] = 1;
    parents[1] = 0;
    w32(0x1018, 4);
    g_vt = 0x800000;
    g_table = 0x850000;
    g_focus_key = UINT64_MAX;
    g_focus_ok = 1;
    g_close_ok = 1;
    callback_calls = accept_calls = foreign_calls = log_calls = 0;
    got_pc = 0;
    got_argc = 0;
    got_arg0 = got_arg1 = 0;
    g_frames = 100;
    g_service = 0;
    g_wheel = 0;
    g_service_page = 0;
    g_service_controller = 0x48000;
    g_service_current = 2;
    g_normal = 0x1000;
    g_page = g_focus = g_owner = g_options = g_dialog = 0;
    w64(0x9152080, 0x310000);
    w64(0x310000, 0x300000);
    w64(g_manager + 0x10, 0x210000);
    w64(0x210000, 0x220000);
    w32(0x210008, 0);
    w32(g_manager + 0x58, 0);
    w64(0x9154338, 0);
    w64(0x9154340, 0);
    w32(0x97F3840, 0);
}
static void service_scene(void) {
    u64 subscriber;
    g_page = mk(ui_path_key("root.normallayer.consoleinventoryring_main"), g_normal, 1);
    g_focus = mk(0x3101, g_page, 1);
    g_focus_key = 0x3101;
    subscriber = mk(0x3102, g_page, 1);
    mk_cb(subscriber, 0x81FB910u);
    sub(subscriber);
    g_service = 1;
    g_wheel = 1;
    g_service_page = g_page;
    w64(0x300000 + 0x108, 0x70001);
}
static void conversation_roots(void) {
    u64 options_sub, dialog_sub;
    g_options = mk(ui_path_key("root.normallayer.consoleconversationoptions_main"), g_normal, 1);
    g_dialog = mk(ui_path_key("root.normallayer.consoleconversationdialog_main"), g_normal, 1);
    options_sub = mk(0x3302, g_options, 1);
    mk_cb(options_sub, 0x81FB910u);
    sub(options_sub);
    dialog_sub = mk(0x3303, g_dialog, 1);
    mk_cb(dialog_sub, 0x8366870u);
    sub(dialog_sub);
    w64(0x9154338, 0x340000);
    w64(0x340000, ui_path_key("root.normallayer.consoleconversationdialog_main"));
    w64(0x9154340, 0x350000);
    w64(0x350000, ui_path_key("root.normallayer.consoleconversationoptions_main"));
    w32(0x97F3840, 0x2A2A);
}
static void conversation_scene(void) {
    conversation_roots();
    g_focus = mk(0x3301, g_options, 1);
    g_focus_key = 0x3301;
}
static void prompt_scene(void) {
    g_page = mk(0x3201, g_normal, 1);
    g_owner = mk(0x3202, g_page, 1);
    mk_cb(g_owner, 0x816AAB0u);
    g_focus = mk(0x3203, g_owner, 1);
    g_focus_key = 0x3203;
    w32(0x300000 + 0xAE8, 1);
    w64(0x300000 + 0xAD8, 0x320000);
    w32(0x320000, 0x55);
    w32(0x320000 + 0xC, 0);
    w32(0x320000 + 0xD0, 2);
}
static int queues_empty(void) {
    return !g_have_pointer && !g_have_hover && !g_world_command && !g_ui_read && !g_ui_count &&
           !g_skill_read && !g_skill_count && !g_item_drag_active && g_cancel;
}
int main(void) {
    /* --- core: service close uses the navigation-stack close 0x816BB90(1,0) --- */
    base(); service_scene();
    CHECK("service-publish-scope", TICK() == 0 && g_close_scope == 1 && g_close_target.kind == UI_CLOSE_SERVICE);
    CHECK("service-snapshot", g_close_target.owner == 0x48000 && g_close_target.context == 0x300000 &&
          g_close_target.model == 0x70001 && g_close_target.generation == 2 &&
          g_close_target.mode == 2 && !g_close_target.frame);
    CHECK("service-no-close-without-key", !callback_calls && !log_calls);
    g_frames++;
    CHECK("service-space-consumed", SPACE() == 1);
    g_frames++;
    CHECK("service-close-callback", TICK() == 1 && callback_calls == 1 && got_pc == 0x816BB90 &&
          got_argc == 2 && got_arg0 == 1 && got_arg1 == 0);
    CHECK("service-close-logged", log_calls == 1);
    CHECK("service-close-foreign", !accept_calls && !foreign_calls);
    CHECK("service-snapshot-cleared", SPACE() == 0 && !g_close_scope && !g_close_target.kind &&
          !g_close_pending.kind);

    /* --- core: a prompt without focus consumes Space and never confirms --- */
    base(); prompt_scene(); g_focus_key = UINT64_MAX;
    CHECK("no-focus-publishes-scope", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    g_frames++;
    CHECK("no-focus-consumes-key", SPACE() == 1);
    g_frames++;
    CHECK("no-focus-no-close-no-confirm", TICK() == 0 && !callback_calls && !accept_calls && !foreign_calls);
    base(); prompt_scene(); g_focus_ok = 0;
    CHECK("focus-getter-failure", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    base(); prompt_scene(); g_focus_key = 0x9999;
    CHECK("prompt-unknown-focus", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);

    /* --- core: a visible subscription outside the page blocks the close --- */
    base(); service_scene();
    {
        u64 outer = mk(0x3103, g_normal, 1);
        mk_cb(outer, 0x8366870u);
        sub(outer);
    }
    CHECK("outer-subscription-blocks", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    g_frames++; SPACE(); g_frames++;
    CHECK("outer-subscription-no-close", TICK() == 0 && !callback_calls);

    /* --- core: a request older than four frames is dropped --- */
    base(); service_scene(); TICK(); g_frames++; SPACE(); g_frames += 5;
    CHECK("stale-five-frames-dropped", TICK() == 0 && !callback_calls);
    base(); service_scene(); TICK(); g_frames++; SPACE(); g_frames += 4;
    CHECK("fresh-four-frames-close", TICK() == 1 && callback_calls == 1);

    /* --- core: switching the service navigation page rejects the request --- */
    base(); service_scene(); TICK(); g_frames++; SPACE();
    w64(0x300000 + 0x108, 0x70002);
    g_frames++;
    CHECK("service-group-change-rejected", TICK() == 0 && !callback_calls && g_close_target.model == 0x70002);
    base(); service_scene(); TICK(); g_frames++; SPACE(); g_service_current = 3; g_frames++;
    CHECK("service-mode-change-rejected", TICK() == 0 && !callback_calls && g_close_target.mode == 3);

    /* --- core: NPC cancel 0x820EF90(owner+0x30,0) with root refs and generation --- */
    base(); conversation_scene();
    CHECK("npc-publish-scope", TICK() == 0 && g_close_scope == 1 && g_close_target.kind == UI_CLOSE_CONVERSATION);
    CHECK("npc-snapshot", g_close_target.owner == g_options && g_close_target.context == g_manager &&
          !g_close_target.model && g_close_target.generation == 0x2A2A);
    g_frames++;
    CHECK("npc-space-consumed", SPACE() == 1);
    g_frames++;
    CHECK("npc-close-callback", TICK() == 1 && callback_calls == 1 && got_pc == 0x820EF90 &&
          got_argc == 2 && got_arg0 == g_options + 0x30 && got_arg1 == 0);
    CHECK("npc-close-no-confirm", !accept_calls && !foreign_calls);

    /* --- core: prompt cancel 0x816A9C0() and never its accept 0x816AAB0 --- */
    base(); prompt_scene();
    CHECK("prompt-publish-scope", TICK() == 0 && g_close_scope == 1 && g_close_target.kind == UI_CLOSE_PROMPT);
    CHECK("prompt-snapshot", g_close_target.owner == g_owner && g_close_target.model == 0x320000 &&
          g_close_target.generation == 0x55 && g_close_target.mode == 2);
    g_frames++; SPACE(); g_frames++;
    CHECK("prompt-cancel-callback", TICK() == 1 && callback_calls == 1 && got_pc == 0x816A9C0 && got_argc == 0);
    CHECK("prompt-never-accepts", !accept_calls);

    /* --- core: a prompt without a cancel/accept owner is not closable --- */
    base(); prompt_scene(); mk_cb(g_owner, 0x8366870u);
    CHECK("prompt-owner-without-accept", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    g_frames++; SPACE(); g_frames++;
    CHECK("prompt-owner-without-accept-no-close", TICK() == 0 && !callback_calls && !accept_calls);

    /* --- core: the prompt model id (generation) must still match --- */
    base(); prompt_scene(); TICK(); g_frames++; SPACE();
    w32(0x320000, 0x56);
    g_frames++;
    CHECK("prompt-id-change-rejected", TICK() == 0 && !callback_calls);

    /* --- core: one close per request even if Space is repeated --- */
    base(); service_scene(); TICK(); g_frames++; SPACE(); SPACE(); g_frames++;
    CHECK("duplicate-request-single-close", TICK() == 1 && callback_calls == 1);
    /* A repeat press must not re-stamp the queued request into a later frame. */
    base(); service_scene(); TICK(); g_frames++; SPACE(); g_frames += 2; SPACE(); g_frames += 3;
    CHECK("duplicate-request-keeps-first-frame", TICK() == 0 && !callback_calls);

    /* --- extra: modal and focus isolation --- */
    base(); service_scene();
    {
        u64 modal = mk(0x3104, 0, 1);
        u64 outer = mk(0x3105, modal, 1);
        mk_cb(outer, 0x8366870u);
        sub(outer);
    }
    CHECK("modal-subscriber-blocks", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    g_frames++; SPACE(); g_frames++;
    CHECK("modal-subscriber-no-close", TICK() == 0 && !callback_calls);
    base(); service_scene();
    {
        u64 hidden = mk(0x3106, g_normal, 0);
        mk_cb(hidden, 0x8366870u);
        sub(hidden);
    }
    CHECK("hidden-subscriber-ignored", TICK() == 0 && g_close_target.kind == UI_CLOSE_SERVICE);
    g_frames++; SPACE(); g_frames++;
    CHECK("hidden-subscriber-still-closes", TICK() == 1 && got_pc == 0x816BB90);
    base(); service_scene(); w32(g_focus + 0x18, 0);
    CHECK("hidden-focus-blocks", TICK() == 0 && !g_close_target.kind);
    base(); service_scene(); parents[g_focus / 0x1000] = g_normal;
    CHECK("focus-outside-page-blocks", TICK() == 0 && !g_close_target.kind);
    base(); service_scene(); g_wheel = 0;
    CHECK("service-wheel-gate", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    base(); service_scene(); w32(0x210008, 0);
    CHECK("service-without-subscribers", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);

    /* --- extra: NPC reference and generation guards --- */
    base(); conversation_scene();
    w64(0x340000, ui_path_key("root.normallayer.consoleconversationoptions_main"));
    CHECK("npc-dialog-ref-mismatch", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    base(); conversation_scene();
    w64(0x350000, ui_path_key("root.normallayer.consoleconversationdialog_main"));
    CHECK("npc-options-ref-mismatch", TICK() == 0 && !g_close_target.kind);
    base(); conversation_scene(); TICK(); g_frames++; SPACE();
    w32(0x97F3840, 0x2A2B);
    g_frames++;
    CHECK("npc-generation-change-rejected", TICK() == 0 && !callback_calls);
    base(); conversation_scene(); w32(g_manager + 0x58, 1);
    CHECK("npc-other-player-not-consumed", TICK() == 0 && !g_close_scope && SPACE() == 0);
    base(); conversation_scene(); w32(g_options + 0x18, 0); w32(g_dialog + 0x18, 0);
    CHECK("npc-hidden-roots", TICK() == 0 && !g_close_scope);
    base(); conversation_scene(); g_focus_key = 0x9999;
    CHECK("npc-unknown-focus", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    base(); conversation_scene();
    {
        u64 stray = mk(0x3304, g_normal, 1);
        mk_cb(stray, 0x8366870u);
        sub(stray);
    }
    CHECK("npc-outer-subscription-blocks", TICK() == 0 && !g_close_target.kind);
    base(); conversation_scene();
    parents[g_focus / 0x1000] = g_dialog;
    w32(g_options + 0x18, 0);
    CHECK("npc-dialog-owner", TICK() == 0 && g_close_target.kind == UI_CLOSE_CONVERSATION &&
          g_close_target.owner == g_dialog);
    g_frames++; SPACE(); g_frames++;
    CHECK("npc-dialog-close-arg", TICK() == 1 && got_arg0 == g_dialog + 0x30);

    /* --- extra: prompt style and player guards --- */
    base(); prompt_scene(); w32(0x320000 + 0xD0, 3);
    CHECK("prompt-style-3-cancellable", TICK() == 0 && g_close_target.kind == UI_CLOSE_PROMPT &&
          g_close_target.mode == 3);
    g_frames++; SPACE(); g_frames++;
    CHECK("prompt-style-3-close", TICK() == 1 && got_pc == 0x816A9C0);
    base(); prompt_scene(); w32(0x320000 + 0xD0, 4);
    CHECK("prompt-style-4-rejected", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    g_frames++; SPACE(); g_frames++;
    CHECK("prompt-style-4-no-close", TICK() == 0 && !callback_calls && !accept_calls);
    base(); prompt_scene(); w32(0x320000 + 0xD0, 1);
    CHECK("prompt-style-1-rejected", TICK() == 0 && !g_close_target.kind);
    base(); prompt_scene(); TICK(); g_frames++; SPACE();
    w32(0x320000 + 0xD0, 3);
    g_frames++;
    CHECK("prompt-style-change-rejected", TICK() == 0 && !callback_calls);
    base(); prompt_scene(); w32(0x320000 + 0xC, UINT32_MAX);
    CHECK("prompt-player-wildcard-cancellable", TICK() == 0 && g_close_target.kind == UI_CLOSE_PROMPT);
    base(); prompt_scene(); w32(0x320000 + 0xC, 1);
    CHECK("prompt-player-other-rejected", TICK() == 0 && !g_close_target.kind);
    base(); prompt_scene(); w64(0x300000 + 0xAD8, 0);
    CHECK("prompt-model-missing", TICK() == 0 && g_close_scope == 1 && !g_close_target.kind);
    base(); prompt_scene(); TICK(); g_frames++; SPACE();
    w64(0x300000 + 0xAD8, 0x321000);
    w32(0x321000, 0x55);
    w32(0x321000 + 0xC, 0);
    w32(0x321000 + 0xD0, 2);
    g_frames++;
    CHECK("prompt-model-change-rejected", TICK() == 0 && !callback_calls && g_close_target.model == 0x321000);
    base(); prompt_scene(); w32(g_owner + 0x18, 0);
    CHECK("prompt-owner-hidden", TICK() == 0 && !g_close_target.kind && !accept_calls);

    /* --- extra: no UI, bogus modal count, cross-layer and branch order --- */
    base();
    CHECK("no-ui-scope", TICK() == 0 && !g_close_scope && SPACE() == 0);
    base(); prompt_scene(); w32(0x300000 + 0xAE8, 33);
    CHECK("prompt-modal-count-bogus", TICK() == 0 && !g_close_scope);
    base(); conversation_scene(); TICK(); g_frames++; SPACE();
    prompt_scene();
    g_frames++;
    CHECK("cross-kind-rejected", TICK() == 0 && !callback_calls && g_close_target.kind == UI_CLOSE_PROMPT);
    base(); service_scene();
    mk(ui_path_key("root.normallayer.consoleconversationdialog_main"), g_normal, 1);
    mk(ui_path_key("root.normallayer.consoleconversationoptions_main"), g_normal, 1);
    CHECK("branch-order-service-first", TICK() == 0 && g_close_target.kind == UI_CLOSE_SERVICE);
    g_frames++; SPACE(); g_frames++;
    CHECK("branch-order-service-closes", TICK() == 1 && got_pc == 0x816BB90);
    base(); service_scene(); TICK(); g_frames++;
    CHECK("duplicate-first-key", SPACE() == 1);
    prompt_scene();
    CHECK("duplicate-second-key", SPACE() == 1);
    g_frames++;
    CHECK("duplicate-no-penetration", TICK() == 0 && !callback_calls && !accept_calls &&
          g_close_target.kind == UI_CLOSE_PROMPT);

    /* --- extra: engine failure, cancel and frame wrap --- */
    base(); service_scene(); TICK(); g_frames++; SPACE(); g_frames++; g_close_ok = 0;
    CHECK("engine-failure-consumes-frame", TICK() == 1 && callback_calls == 1 &&
          !g_close_scope && !g_close_pending.kind);
    CHECK("engine-failure-clears-target", !g_close_target.kind && SPACE() == 0);
    base(); service_scene(); TICK();
    CHECK("cancel-clears-scope", g_close_scope == 1);
    native_world_cancel();
    CHECK("cancel-clears-snapshot", !g_close_scope && !g_close_target.kind && !g_close_pending.kind &&
          SPACE() == 0);
    base(); service_scene(); TICK();
    g_have_pointer = 1;
    g_have_hover = 1;
    g_world_command = 3;
    g_ui_count = 2;
    g_skill_count = 1;
    g_item_drag_active = 1;
    native_world_cancel();
    CHECK("cancel-clears-input-queues", queues_empty());
    base(); service_scene(); TICK(); g_frames++; SPACE();
    CHECK("cancel-pending-queued", g_close_pending.kind == UI_CLOSE_SERVICE);
    native_world_cancel();
    g_frames++;
    CHECK("cancel-drops-pending", TICK() == 0 && !callback_calls);
    base(); service_scene(); TICK(); g_frames = UINT32_MAX - 1; SPACE(); g_frames = 2;
    CHECK("frame-wrap-fresh", TICK() == 1 && callback_calls == 1);
    base(); service_scene(); TICK();
    for (int i = 0; i < 5; i++) {
        g_frames++;
        CHECK("idle-republish-no-close", TICK() == 0 && !callback_calls);
    }
    printf("%d checks; %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
"""


def close_slice(source: str) -> str:
    """The published Space close snapshot, only when this tree has the close path."""
    if "UiCloseTarget" not in source:
        raise SystemExit("production source has no UiCloseTarget close path")
    return source[source.index("typedef struct {\n    u64 owner, context, model;"):
                  source.index("/* Last click's goal kind")]


def main() -> int:
    source = SOURCE.read_text("utf-8")
    declarations = source[source.index("/* Service ABI whitelist"):
                            source.index("static int ui_service_state(")]
    code = (PRELUDE + close_slice(source) + declarations + STUBS +
            "\n".join(function(source, name) for name in NAMES) + CASES)
    OUT.mkdir(parents=True, exist_ok=True)
    c, exe = OUT / "ui-close.c", OUT / "ui-close.exe"
    c.write_text(code, "utf-8")
    cc = "D:/workspace/msys2/msys64/clang64/bin/clang.exe"
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout, end="")
    record = {"source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "scope": __doc__, "returncode": result.returncode,
              "checks": 0, "failures": -1, "stdout": result.stdout}
    for line in result.stdout.splitlines():
        if "checks;" in line and line.endswith("failures"):
            head, tail = line.split("checks;", 1)
            record["checks"] = int(head.strip())
            record["failures"] = int(tail.split()[0])
    (OUT / "result.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), "utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())