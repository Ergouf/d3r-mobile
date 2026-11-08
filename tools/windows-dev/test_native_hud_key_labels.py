"""Run the production HUD keybinding label hook against a fake CPU and call stubs.

Offline regression for 0078 world_label: which native text-setter calls may be
relabelled with left/right/1-4, that the label goes through the game's own
inverse binding lookup (0x840C650), and that the real guest_call keeps its
nesting depth balanced on success and on an incomplete guest call.
Live HUD content is verified separately through SDL input.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference/ScarletNX-src/src/nx/runtime/native_world.c"
OUT = ROOT / "out/windows/kbm/session/hud-key-labels"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kbm_source import function, read_runtime

NAMES = ["guest_call", "world_label"]

PRELUDE = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef union { u8 b[16]; u64 d[2]; float f[4]; } V128;
/* The guest CPU fields the label hook and guest_call read. */
typedef struct CPU {
    u64 x[32];
    u64 pc;
    u32 n, z, cf, vf;
    V128 v[32];
    u32 poll;
} CPU;
typedef void (*GuestFn)(CPU* c, u64 entry);
typedef struct { u64 x0; float f0; } GuestResult;
static unsigned char memory[0x100000];
static u64 g_stack_top;
static int g_enabled = 1;
static unsigned g_guest_call_depth;
static GuestFn g_label_original;
static u64 g_footer_object;
static char g_footer_original[512], g_footer_display[512];
static int warn_calls, lookup_calls;
#define GP(a) (memory + (a))
#define WARN(...) do { warn_calls++; if (0) printf(__VA_ARGS__); } while (0)
#define LOG(...) do { if (0) printf(__VA_ARGS__); } while (0)
static int kbm_readable(u64 a, size_t n) { return a && a < sizeof memory && n <= sizeof memory - a; }
static int kbm_read32(u64 a, u32* v) { if (!kbm_readable(a, 4)) return 0; memcpy(v, GP(a), 4); return 1; }
static int kbm_read64(u64 a, u64* v) { if (!kbm_readable(a, 8)) return 0; memcpy(v, GP(a), 8); return 1; }
static void w32(u64 a, u32 v) { memcpy(GP(a), &v, 4); }
static void w64(u64 a, u64 v) { memcpy(GP(a), &v, 8); }
"""

STUBS = r"""
/* The only guest function these tests let the real guest_call reach is the
   inverse binding lookup; everything else must be reported as unresolvable. */
static const char* backend_kbm_key(int index) {
    static const char* keys[] = {"1", "2", "3", "4", "Q", "T", "C", "S", "J", "P", "M", "Escape"};
    return index >= 0 && index < 12 ? keys[index] : "?";
}
static u32 query_slot;
static int query_incomplete;
static int query_calls;
static u32 got_binding;
static u64 got_player;
static unsigned observed_depth;
static void query_fn(CPU* c, u64 entry) {
    (void)entry;
    query_calls++;
    observed_depth = g_guest_call_depth;
    got_binding = (u32)c->x[0];
    got_player = c->x[1];
    if (query_incomplete) { c->pc = 0x777000; return; }
    c->x[0] = query_slot;
    c->pc = 0;
}
static GuestFn snx_lookup(const CPU* c, u64 pc) {
    (void)c;
    lookup_calls++;
    return pc == 0x840C650 ? query_fn : NULL;
}
/* The production text setter is the only observer of the label argument. */
static int label_calls;
static u64 label_x1;
static const char* label_text;
static void label_record(CPU* c, u64 entry) {
    (void)entry;
    label_calls++;
    label_x1 = c->x[1];
    label_text = c->x[1] < sizeof memory ? (const char*)GP(c->x[1]) : NULL;
}
"""
CASES = r"""
static CPU cpu;
static const char* expect_label[6] = {
    "\xE5\xB7\xA6\xE9\x94\xAE", "\xE5\x8F\xB3\xE9\x94\xAE", "1", "2", "3", "4"
};
static int failures, checks;
#define CHECK(name, condition) do { checks++; if (!(condition)) { printf("FAIL %s\n", name); failures++; } } while (0)
#define ORIGINAL 0x50000u
/* Fixture: local player, its HUD input-player copy at +0xDB74, the label widget
   holding that copy at +0x3E0, the text setter's vtable slot and a binding cell. */
static void fixture(void) {
    memset(memory, 0, sizeof memory);
    g_enabled = 1;
    g_stack_top = 0x90000;
    g_guest_call_depth = 0;
    g_label_original = label_record;
    memset(&cpu, 0, sizeof cpu);
    query_slot = 0;
    query_incomplete = 0;
    query_calls = 0;
    got_binding = 0xFFFFFFFFu;
    got_player = 0;
    observed_depth = 0xFFFFFFFFu;
    label_calls = 0;
    label_x1 = 0;
    label_text = NULL;
    warn_calls = 0;
    lookup_calls = 0;
    w32(0x10000, 0);
    w32(0x10000 + 0xDB74, 0x21);
    w32(0x20000 + 0x3E0, 0x21);
    w64(0x20000, 0x30000);
    w64(0x30000 + 0x110, LABEL_PC);
    w32(0x40000, 3);
    strcpy((char*)GP(ORIGINAL), "original");
    cpu.x[0] = 0x20000;
    cpu.x[1] = ORIGINAL;
    cpu.x[2] = 0;
    cpu.x[19] = 0x10000;
    cpu.x[22] = 0x40028;
    cpu.x[30] = HUD_LABEL_RETURN;
    cpu.poll = 7;
}
static int labelled(u32 slot) {
    return label_calls == 1 && label_x1 == g_stack_top - 0x17000 && label_text &&
           !strcmp(label_text, expect_label[slot]) && g_guest_call_depth == 0 &&
           !strcmp((const char*)GP(ORIGINAL), "original");
}
static void reject(const char* name, u64 entry, int expected_queries) {
    label_calls = 0;
    label_x1 = 0;
    label_text = NULL;
    world_label(&cpu, entry);
    CHECK(name, label_calls == 1 && label_x1 == ORIGINAL && label_text &&
                !strcmp(label_text, "original") && query_calls == expected_queries &&
                g_guest_call_depth == 0);
}
int main(void) {
    u64 args[2];
    GuestResult r = {0, 0.0f};
    int ok;

    /* --- the six real slots, whatever the physical binding order --- */
    for (u32 slot = 0; slot < 6; slot++) {
        fixture();
        query_slot = slot;
        world_label(&cpu, LABEL_PC);
        CHECK("logical-slot-label", labelled(slot) && query_calls == 1 && observed_depth == 1 &&
              got_binding == 3 && got_player == 0x10000);
    }
    /* The potion caller uses x20 and has no binding-cell stack frame. */
    fixture();
    cpu.x[30] = HUD_POTION_LABEL_RETURN;
    cpu.x[20] = cpu.x[19];
    cpu.x[19] = cpu.x[22] = 0;
    world_label(&cpu, LABEL_PC);
    CHECK("potion-uses-x20-without-binding-cell", label_calls == 1 && label_text &&
          !strcmp(label_text, "Q") && query_calls == 0);
    fixture();
    cpu.x[30] = HUD_POTION_LABEL_RETURN;
    cpu.x[20] = 0x60000;
    w32(0x60000, 1);
    reject("potion-rejects-foreign-player", LABEL_PC, 0);
    fixture();
    cpu.x[30] = HUD_POTION_LABEL_RETURN;
    cpu.x[20] = 0x60000;
    w32(0x60000 + 0xDB74, 0x22);
    reject("potion-rejects-player-copy-mismatch", LABEL_PC, 0);
    fixture();
    query_slot = 2;
    world_label(&cpu, LABEL_PC);
    CHECK("replacement-buffer-written", !memcmp(GP(g_stack_top - 0x17000), expect_label[2],
          strlen(expect_label[2]) + 1));
    CHECK("source-cpu-not-clobbered", cpu.poll == 7 && cpu.x[19] == 0x10000 &&
          cpu.x[22] == 0x40028 && cpu.x[30] == HUD_LABEL_RETURN && cpu.x[2] == 0);
    {
        static const u32 mapped[8] = {3, 0, 5, 1, 4, 2, 7, 6};
        for (u32 binding = 0; binding < 8; binding++) {
            fixture();
            w32(0x40000, binding);
            query_slot = mapped[binding];
            world_label(&cpu, LABEL_PC);
            CHECK("binding-queried-as-itself", query_calls == 1 && got_binding == binding &&
                  observed_depth == 1);
            if (mapped[binding] < 6) CHECK("binding-follows-native-slot", labelled(mapped[binding]));
            else CHECK("binding-past-six-passes-through", label_calls == 1 && label_x1 == ORIGINAL &&
                       !strcmp(label_text, "original"));
        }
    }

    /* --- the HUD input-player copy, not a constant, must match --- */
    fixture();
    w32(0x1DB74, 0x2A);
    w32(0x203E0, 0x2A);
    query_slot = 4;
    world_label(&cpu, LABEL_PC);
    CHECK("label-player-nonzero-matching-allowed", labelled(4) && query_calls == 1);
    fixture();
    w32(0x1DB74, 0);
    w32(0x203E0, 0);
    query_slot = 0;
    world_label(&cpu, LABEL_PC);
    CHECK("label-player-zero-matching-allowed", labelled(0) && query_calls == 1);

    /* --- every other text call is passed through untouched --- */
    fixture();
    reject("reject-wrong-entry", LABEL_PC + 4, 0);
    fixture();
    cpu.x[30] = 0;
    reject("reject-wrong-return", LABEL_PC, 0);
    fixture();
    cpu.x[2] = 1;
    reject("reject-x2-not-zero", LABEL_PC, 0);
    fixture();
    g_enabled = 0;
    reject("reject-disabled", LABEL_PC, 0);
    fixture();
    w32(0x10000, 1);
    reject("reject-player-not-local", LABEL_PC, 0);
    fixture();
    cpu.x[19] = 0;
    reject("reject-player-unreadable", LABEL_PC, 0);
    fixture();
    cpu.x[19] = 0xFFFFF0;
    reject("reject-input-player-unreadable", LABEL_PC, 0);
    fixture();
    w32(0x203E0, 0x22);
    reject("reject-label-player-mismatch", LABEL_PC, 0);
    fixture();
    w32(0x203E0, 0);
    reject("reject-label-player-zero-vs-input", LABEL_PC, 0);
    fixture();
    w32(0x1DB74, 0);
    reject("reject-input-player-zero-vs-label", LABEL_PC, 0);
    fixture();
    w64(0x30000 + 0x110, LABEL_PC + 4);
    reject("reject-foreign-text-setter", LABEL_PC, 0);
    fixture();
    cpu.x[0] = 0x200000;
    reject("reject-label-unreadable", LABEL_PC, 0);
    fixture();
    w32(0x40000, 8);
    reject("reject-binding-out-of-range", LABEL_PC, 0);
    fixture();
    cpu.x[22] = 0x20;
    reject("reject-binding-frame", LABEL_PC, 0);
    fixture();
    cpu.x[22] = 0x28;
    reject("reject-binding-unreadable", LABEL_PC, 0);
    fixture();
    g_stack_top = 0x10000;
    reject("reject-stack-region", LABEL_PC, 0);
    fixture();
    g_stack_top = 0x17000;
    query_slot = 1;
    reject("reject-replacement-unreadable", LABEL_PC, 1);
    fixture();
    g_guest_call_depth = 1;
    query_slot = 0;
    label_calls = 0;
    label_x1 = 0;
    label_text = NULL;
    world_label(&cpu, LABEL_PC);
    CHECK("no-nested-guest-call", label_calls == 1 && label_x1 == ORIGINAL && query_calls == 0 &&
          g_guest_call_depth == 1 && !strcmp(label_text, "original"));

    /* --- the game lookup's own outcomes --- */
    fixture();
    query_incomplete = 1;
    query_slot = 2;
    world_label(&cpu, LABEL_PC);
    CHECK("incomplete-lookup-keeps-text", query_calls == 1 && observed_depth == 1 &&
          label_calls == 1 && label_x1 == ORIGINAL && !strcmp(label_text, "original") &&
          g_guest_call_depth == 0 && warn_calls == 1);
    fixture();
    query_slot = 6;
    world_label(&cpu, LABEL_PC);
    CHECK("logical-six-keeps-text", query_calls == 1 && label_x1 == ORIGINAL &&
          !strcmp(label_text, "original"));
    fixture();
    query_slot = 0xFFFF;
    world_label(&cpu, LABEL_PC);
    CHECK("logical-wild-keeps-text", query_calls == 1 && label_x1 == ORIGINAL &&
          !strcmp(label_text, "original"));

    /* --- the real guest_call keeps its depth balanced --- */
    args[0] = 5;
    args[1] = 0x10000;
    fixture();
    query_slot = 5;
    ok = guest_call(&cpu, 0x840C650, args, 2, NULL, 0, &r);
    CHECK("direct-call-success-depth", ok == 1 && r.x0 == 5 && observed_depth == 1 &&
          g_guest_call_depth == 0 && query_calls == 1);
    fixture();
    query_incomplete = 1;
    ok = guest_call(&cpu, 0x840C650, args, 2, NULL, 0, &r);
    CHECK("direct-call-incomplete-depth", ok == 0 && observed_depth == 1 &&
          g_guest_call_depth == 0 && warn_calls == 1);
    fixture();
    g_guest_call_depth = 1;
    query_slot = 1;
    ok = guest_call(&cpu, 0x840C650, args, 2, NULL, 0, &r);
    CHECK("direct-call-nested-depth", ok == 1 && observed_depth == 2 && g_guest_call_depth == 1);
    fixture();
    ok = guest_call(&cpu, 0x123456, args, 2, NULL, 0, &r);
    CHECK("direct-call-unresolved-depth", ok == 0 && g_guest_call_depth == 0 && lookup_calls == 1);

    /* Footer setter calls share this hook and keep their pad template cached. */
    fixture();
    cpu.x[30] = 0;
    strcpy((char*)GP(ORIGINAL), "{icon:button2} Close");
    world_label(&cpu, LABEL_PC);
    CHECK("footer-setter-rebuilds-text", label_calls == 1 && !strcmp(label_text, "[Esc] Close"));
    CHECK("footer-preserves-template-owner", g_footer_object == cpu.x[0] &&
          !strcmp(g_footer_original, "{icon:button2} Close") && !strcmp(g_footer_display, "[Esc] Close"));

    printf("%d checks; %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
"""


def defines(source: str) -> str:
    """The HUD label entry and its return address, as the production build has them."""
    lines = []
    for name in ("LABEL_PC", "HUD_LABEL_RETURN", "HUD_POTION_LABEL_RETURN"):
        found = re.search(r"^#define " + name + r" [^\n]*$", source, re.M)
        if not found:
            raise SystemExit("missing define " + name)
        lines.append(found.group(0))
    return "\n".join(lines) + "\n"


def main() -> int:
    source = read_runtime()
    label = function(source, "world_label")
    if "0x840C650" not in label:
        raise SystemExit("world_label no longer uses the native binding lookup")
    if "0xDB74" not in label or "0x3E0" not in label:
        raise SystemExit("world_label no longer compares the HUD input-player copy")
    code = (PRELUDE + defines(source) + STUBS + function(source, "guest_call")
            + function(source, "footer_transform") + label + CASES)
    OUT.mkdir(parents=True, exist_ok=True)
    c, exe = OUT / "hud-key-labels.c", OUT / "hud-key-labels.exe"
    c.write_text(code, "utf-8")
    cc = "D:/workspace/msys2/msys64/clang64/bin/clang.exe"
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout, end="")
    record = {"source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
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
