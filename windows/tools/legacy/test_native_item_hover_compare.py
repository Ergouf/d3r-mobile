"""Test 0077 item hover and held-Alt helpers against bounded C boundary stubs.

This exercises extracted C source, not a game binary or visible comparison
content. ui_item_context supplies the already-validated focus/modal gate as a
stub; native item/model callbacks are simulated only at their call boundary.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from test_hover_wheel import function

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "windows/source/ScarletNX-src/src/nx/runtime/native_world.c"
OUTPUT = ROOT / "out/windows/kbm/session/native-item-hover-compare-0077"
COMPILER = "D:/workspace/msys2/msys64/clang64/bin/clang.exe"
FUNCTIONS = ("native_ui_compare_set", "ui_item_hover", "ui_compare_tick")

PRELUDE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { u64 registers[31]; } CPU;
typedef struct { u64 x0; } GuestResult;
typedef struct { const CPU* cpu; u64 map; float point[2]; int hover; } UiPick;
typedef struct { u64 owner,side[2]; int stash; } UiItemContext;
typedef struct { u32 handle; u64 control; u32 index; int side; } UiItem;
typedef struct { u64 pc,arguments[2]; unsigned count; } NativeCall;
enum { OWNER_A=0x1000,OWNER_B=0x2000,SIDE_A=0x3000,SIDE_B=0x4000,
       CONTROL_A=0x5000,CONTROL_B=0x6000,CONTEXT=0x7000,MAP=0x8000 };
static unsigned char memory[0x10000];
static CPU test_cpu;
static UiItemContext context_fixture;
static UiItem item_fixture;
static NativeCall calls[128];
static int call_count,context_calls,build_calls,pick_calls,blocked,pick_miss;
static int g_compare_requested;
static u64 g_compare_owner;
static u32 g_compare_restore;
static u64 failed_pc,failed_read32,failed_read64;
static int getter_zero,setter_updates,compare_updates,restore_updates,wrong_handle,fail_readback;
static u32 button_context;
static unsigned abi_errors,unexpected_calls;
static char last_log[256];
#define LOG(...) do { snprintf(last_log,sizeof last_log,__VA_ARGS__); } while(0)
static int readable(u64 address,size_t length) {
    return address && address<sizeof memory && length<=sizeof memory-address;
}
static u32 value32(u64 address) {
    u32 value=0;
    if(readable(address,sizeof value))memcpy(&value,memory+address,sizeof value);
    return value;
}
static void write32(u64 address,u32 value) {
    if(!readable(address,sizeof value)){abi_errors++;return;}
    memcpy(memory+address,&value,sizeof value);
}
static void write64(u64 address,u64 value) {
    if(!readable(address,sizeof value)){abi_errors++;return;}
    memcpy(memory+address,&value,sizeof value);
}
static int read32(u64 address,u32* value) {
    if(address==failed_read32||!readable(address,sizeof *value))return 0;
    memcpy(value,memory+address,sizeof *value);return 1;
}
static int read64(u64 address,u64* value) {
    if(address==failed_read64||!readable(address,sizeof *value))return 0;
    memcpy(value,memory+address,sizeof *value);return 1;
}
static int ui_item_context(UiPick* pick,UiItemContext* context) {
    context_calls++;
    if(pick->cpu!=&test_cpu||pick->map!=MAP)abi_errors++;
    if(blocked)return 0;
    *context=context_fixture;return 1;
}
static void ui_build_children(u64 map) {
    build_calls++;if(map!=MAP)abi_errors++;
}
static int ui_item_pick(UiPick* pick,const UiItemContext* context,UiItem* item) {
    pick_calls++;
    if(pick->map!=MAP||context->owner!=context_fixture.owner)abi_errors++;
    if(pick_miss)return 0;
    *item=item_fixture;return 1;
}
static int guest_call(const CPU* cpu,u64 pc,const u64* arguments,unsigned count,
                      const float* floats,unsigned float_count,GuestResult* result) {
    if(cpu!=&test_cpu||floats||float_count||count>2||call_count>=128){abi_errors++;return 0;}
    NativeCall* recorded=&calls[call_count++];
    recorded->pc=pc;recorded->count=count;
    for(unsigned index=0;index<count;index++)recorded->arguments[index]=arguments[index];
    if(pc==0x8170BD0) {
        if(arguments||count||!result){abi_errors++;return 0;}
        if(failed_pc==pc)return 0;
        result->x0=getter_zero?0:CONTEXT;return 1;
    }
    if(pc==0x81C0820) {
        if(count!=2||arguments[0]!=CONTEXT||arguments[1]!=5||!result){abi_errors++;return 0;}
        if(failed_pc==pc)return 0;
        result->x0=button_context;return 1;
    }
    if(pc==0x838A6E0) {
        if(count!=2||arguments[0]!=item_fixture.control||arguments[1]!=item_fixture.index||result){abi_errors++;return 0;}
        if(failed_pc==pc)return 0;
        if(setter_updates) {
            write32(item_fixture.control+0x1E0,item_fixture.index);
            write32(context_fixture.side[item_fixture.side]+0x48,item_fixture.handle+(wrong_handle?1u:0u));
        }
        return 1;
    }
    if(pc==0x8373750||pc==0x81FC220) {
        if(count!=2||arguments[0]!=context_fixture.owner||result||
           (pc==0x8373750&&arguments[1]!=0)||(pc==0x81FC220&&arguments[1]>1)) {abi_errors++;return 0;}
        if(failed_pc==pc)return 0;
        if(pc==0x8373750&&compare_updates)write32(arguments[0]+0x154,1-value32(arguments[0]+0x154));
        if(pc==0x81FC220&&restore_updates)write32(arguments[0]+0x154,(u32)arguments[1]);
        if(fail_readback)failed_read32=arguments[0]+0x154;
        return 1;
    }
    unexpected_calls++;return 0;
}
'''

CASES = r'''
static unsigned checks,failures;
static void check_result(const char* name,int passed,const char* expected) {
    checks++;
    printf("%s %s\n",passed?"PASS":"FAIL",name);
    if(passed)return;
    failures++;
    printf("  expected=%s actual: requested=%d owner=%llx restore=%u modeA=%u modeB=%u calls=%d blocked=%d button_context=%u selected=%u\n",
           expected,g_compare_requested,(unsigned long long)g_compare_owner,g_compare_restore,
           value32(OWNER_A+0x154),value32(OWNER_B+0x154),call_count,blocked,button_context,
           value32(context_fixture.side[0]+0x48));
    for(int index=0;index<call_count;index++)printf("  call[%d]=%llx(%llx,%llx) argc=%u\n",index,
        (unsigned long long)calls[index].pc,(unsigned long long)calls[index].arguments[0],
        (unsigned long long)calls[index].arguments[1],calls[index].count);
}
#define CHECK(name,condition) check_result(name,!!(condition),#condition)
static void reset(void) {
    memset(memory,0,sizeof memory);memset(calls,0,sizeof calls);memset(last_log,0,sizeof last_log);
    context_fixture=(UiItemContext){OWNER_A,{SIDE_A,SIDE_B},0};
    item_fixture=(UiItem){0x12345678,CONTROL_A,3,0};
    call_count=context_calls=build_calls=pick_calls=blocked=pick_miss=0;
    g_compare_requested=0;g_compare_owner=0;g_compare_restore=0;
    failed_pc=failed_read32=failed_read64=0;
    getter_zero=wrong_handle=fail_readback=0;
    setter_updates=compare_updates=restore_updates=1;button_context=9;
    write32(OWNER_A+0x154,0);write32(OWNER_B+0x154,0);
    write32(SIDE_A+0x48,0x11111111);write32(SIDE_B+0x48,0x22222222);
    write64(CONTROL_A+0x48,SIDE_A);write64(CONTROL_B+0x48,SIDE_B);
    write32(CONTROL_A+0x1E0,1);write32(CONTROL_B+0x1E0,2);
}
static int hover(void) {
    UiPick pick={.cpu=&test_cpu,.map=MAP,.point={100,200},.hover=1};
    return ui_item_hover(&pick);
}
static void tick(void) { ui_compare_tick(&test_cpu,MAP); }
static void enter(void) { native_ui_compare_set(1);tick(); }
static int entry_calls(int offset,u64 owner) {
    return call_count>=offset+3&&calls[offset].pc==0x8170BD0&&calls[offset].count==0&&
           calls[offset+1].pc==0x81C0820&&calls[offset+1].arguments[0]==CONTEXT&&
           calls[offset+1].arguments[1]==5&&calls[offset+2].pc==0x8373750&&
           calls[offset+2].arguments[0]==owner&&calls[offset+2].arguments[1]==0;
}
static int restore_call(int offset,u64 owner,u32 desired) {
    return call_count==offset+1&&calls[offset].pc==0x81FC220&&calls[offset].count==2&&
           calls[offset].arguments[0]==owner&&calls[offset].arguments[1]==desired;
}
static void test_hover(void) {
    reset();CHECK("hover-side0-is-handled",hover()==1);
    CHECK("hover-side0-exact-setter-and-row",call_count==1&&calls[0].pc==0x838A6E0&&calls[0].arguments[0]==CONTROL_A&&calls[0].arguments[1]==3);
    CHECK("hover-builds-and-picks-once",build_calls==1&&pick_calls==1);
    CHECK("hover-selects-without-compare-or-accept",value32(CONTROL_A+0x1E0)==3&&g_compare_owner==0&&!g_compare_requested);
    reset();item_fixture.side=1;item_fixture.control=CONTROL_B;item_fixture.index=7;
    CHECK("hover-side1-uses-own-binding",hover()==1&&call_count==1&&calls[0].pc==0x838A6E0&&calls[0].arguments[0]==CONTROL_B&&calls[0].arguments[1]==7);
    reset();write32(CONTROL_A+0x1E0,3);
    CHECK("hover-already-selected-does-not-repeat",hover()==1&&hover()==1&&!call_count);
    reset();write64(CONTROL_A+0x48,SIDE_B);
    CHECK("hover-side0-rejects-other-side-binding",!hover()&&!call_count);
    reset();item_fixture.side=1;item_fixture.control=CONTROL_B;write64(CONTROL_B+0x48,SIDE_A);
    CHECK("hover-side1-rejects-other-side-binding",!hover()&&!call_count);
    reset();write64(CONTROL_A+0x48,0x9000);
    CHECK("hover-rejects-unrelated-binding",!hover()&&!call_count);
    reset();failed_read64=CONTROL_A+0x48;
    CHECK("hover-unreadable-binding-does-not-call",!hover()&&!call_count);
    reset();pick_miss=1;
    CHECK("hover-target-miss-does-not-call",!hover()&&!call_count);
    reset();item_fixture.control=0;
    CHECK("hover-missing-control-does-not-call",!hover()&&!call_count);
    reset();failed_read32=CONTROL_A+0x1E0;
    CHECK("hover-unreadable-selection-does-not-call",!hover()&&!call_count);
    reset();item_fixture.control=sizeof memory;
    CHECK("hover-out-of-bounds-control-does-not-call",!hover()&&!call_count);
    reset();blocked=1;
    CHECK("hover-service-context-failure-stops-before-pick",!hover()&&!call_count&&!build_calls&&!pick_calls);
    reset();blocked=2;
    CHECK("hover-modal-context-failure-stops-before-pick",!hover()&&!call_count&&!build_calls&&!pick_calls);
    reset();failed_pc=0x838A6E0;
    CHECK("hover-native-failure-is-consumed-without-confirm",hover()==1&&call_count==1&&calls[0].pc==0x838A6E0&&value32(CONTROL_A+0x1E0)==1);
    CHECK("hover-native-failure-reports-incomplete",strstr(last_log,"incomplete")!=NULL);
    reset();setter_updates=0;
    CHECK("hover-no-selection-change-has-no-fallback",hover()==1&&call_count==1&&calls[0].pc==0x838A6E0&&strstr(last_log,"incomplete"));
    reset();wrong_handle=1;
    CHECK("hover-handle-mismatch-has-no-fallback",hover()==1&&call_count==1&&calls[0].pc==0x838A6E0&&strstr(last_log,"incomplete"));
}
static void test_compare_lifecycle(void) {
    reset();native_ui_compare_set(1);
    CHECK("frontend-set-only-publishes-held",__atomic_load_n(&g_compare_requested,__ATOMIC_ACQUIRE)==1&&!context_calls&&!call_count&&!g_compare_owner);
    native_ui_compare_set(0);
    CHECK("frontend-release-only-publishes-clear",!__atomic_load_n(&g_compare_requested,__ATOMIC_ACQUIRE)&&!context_calls&&!call_count);
    tick();CHECK("idle-without-owner-does-no-work",!context_calls&&!call_count);
    reset();enter();
    CHECK("held-entry-uses-full-native-compare-branch",call_count==3&&entry_calls(0,OWNER_A));
    CHECK("held-entry-saves-owner-and-original-mode",g_compare_owner==OWNER_A&&g_compare_restore==0&&value32(OWNER_A+0x154)==1);
    for(unsigned frame=0;frame<16;frame++)tick();
    CHECK("held-multiple-frames-do-not-toggle-again",call_count==3&&value32(OWNER_A+0x154)==1&&g_compare_restore==0);
    native_ui_compare_set(0);
    CHECK("frontend-release-keeps-pending-owner-until-tick",g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==1&&call_count==3);
    tick();CHECK("release-restores-with-native-model-setter",restore_call(3,OWNER_A,0)&&value32(OWNER_A+0x154)==0&&!g_compare_owner);
    tick();CHECK("released-multiple-frames-do-not-repeat",call_count==4);
    reset();write32(OWNER_A+0x154,1);enter();
    CHECK("initial-compare-mode-is-kept-without-action",!call_count&&g_compare_owner==OWNER_A&&g_compare_restore==1);
    native_ui_compare_set(0);tick();
    CHECK("initial-compare-mode-survives-release",!call_count&&value32(OWNER_A+0x154)==1&&!g_compare_owner);
    reset();write32(OWNER_A+0x154,1);enter();write32(OWNER_A+0x154,0);native_ui_compare_set(0);tick();
    CHECK("restore-uses-saved-mode-one-not-hardcoded-zero",restore_call(0,OWNER_A,1)&&value32(OWNER_A+0x154)==1&&!g_compare_owner);
    reset();write32(OWNER_A+0x154,2);enter();
    CHECK("unknown-compare-mode-does-not-capture-owner",!call_count&&!g_compare_owner);
    reset();failed_read32=OWNER_A+0x154;enter();
    CHECK("unreadable-compare-mode-does-not-capture-owner",!call_count&&!g_compare_owner);
}
static void test_release_selection_boundary(void) {
    reset();enter();button_context=27;native_ui_compare_set(0);tick();
    CHECK("release-after-unknown-context-still-restores",restore_call(3,OWNER_A,0)&&value32(OWNER_A+0x154)==0&&!g_compare_owner);
    reset();enter();write32(SIDE_A+0x48,UINT32_MAX);native_ui_compare_set(0);tick();
    CHECK("release-after-empty-selection-still-restores",restore_call(3,OWNER_A,0)&&value32(OWNER_A+0x154)==0&&!g_compare_owner);
    reset();enter();button_context=27;write32(SIDE_A+0x48,UINT32_MAX);native_ui_compare_set(0);tick();
    CHECK("release-after-unknown-and-empty-sends-only-setter",restore_call(3,OWNER_A,0)&&value32(OWNER_A+0x154)==0&&!g_compare_owner);
    reset();enter();button_context=27;failed_pc=0x8170BD0;failed_read32=SIDE_A+0x48;native_ui_compare_set(0);tick();
    CHECK("release-does-not-read-selection-or-button-context",restore_call(3,OWNER_A,0)&&value32(OWNER_A+0x154)==0&&!g_compare_owner);
}
static void test_context_and_owner_isolation(void) {
    reset();blocked=2;enter();
    CHECK("modal-blocks-held-entry",!call_count&&!g_compare_owner&&value32(OWNER_A+0x154)==0);
    reset();enter();blocked=2;native_ui_compare_set(0);
    for(unsigned frame=0;frame<4;frame++)tick();
    CHECK("modal-pauses-release-without-penetration",call_count==3&&g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==1);
    blocked=0;tick();
    CHECK("return-to-inventory-restores-after-modal",restore_call(3,OWNER_A,0)&&!g_compare_owner&&value32(OWNER_A+0x154)==0);
    reset();enter();blocked=2;tick();blocked=0;tick();
    CHECK("modal-return-while-held-does-not-retoggle",call_count==3&&g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==1);
    reset();blocked=1;enter();
    CHECK("service-context-blocks-held-entry",!call_count&&!g_compare_owner);
    reset();enter();blocked=1;native_ui_compare_set(0);tick();
    CHECK("service-context-blocks-release",call_count==3&&g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==1);
    blocked=0;tick();CHECK("inventory-return-restores-after-service",restore_call(3,OWNER_A,0)&&!g_compare_owner);
    reset();context_fixture.stash=1;enter();
    CHECK("stash-cannot-start-compare",!call_count&&!g_compare_owner&&value32(OWNER_A+0x154)==0);
    reset();enter();context_fixture.stash=1;native_ui_compare_set(0);tick();
    CHECK("stash-does-not-restore-through-old-owner",call_count==3&&!g_compare_owner&&value32(OWNER_A+0x154)==1);
    reset();enter();context_fixture.owner=OWNER_B;native_ui_compare_set(0);tick();
    CHECK("owner-change-on-release-touches-neither-owner",call_count==3&&!g_compare_owner&&value32(OWNER_A+0x154)==1&&value32(OWNER_B+0x154)==0);
    reset();enter();context_fixture.owner=OWNER_B;tick();
    CHECK("owner-change-while-held-first-drops-old-owner",call_count==3&&!g_compare_owner&&value32(OWNER_A+0x154)==1&&value32(OWNER_B+0x154)==0);
    tick();CHECK("next-held-frame-only-uses-new-owner",call_count==6&&entry_calls(3,OWNER_B)&&g_compare_owner==OWNER_B&&value32(OWNER_A+0x154)==1);
    native_ui_compare_set(0);tick();
    CHECK("new-owner-release-cannot-restore-old-owner",restore_call(6,OWNER_B,0)&&!g_compare_owner&&value32(OWNER_A+0x154)==1&&value32(OWNER_B+0x154)==0);
}
static void test_entry_rejection_and_engine_failures(void) {
    reset();button_context=27;enter();
    CHECK("unknown-button3-context-never-enters-compare",call_count==2&&calls[0].pc==0x8170BD0&&calls[1].pc==0x81C0820&&value32(OWNER_A+0x154)==0);
    reset();button_context=10;enter();
    CHECK("return-compare-context-cannot-enter-from-mode-zero",call_count==2&&value32(OWNER_A+0x154)==0);
    reset();write32(SIDE_A+0x48,UINT32_MAX);enter();
    CHECK("empty-side-zero-selection-blocks-entry-before-context",!call_count&&value32(OWNER_A+0x154)==0);
    reset();failed_read32=SIDE_A+0x48;enter();
    CHECK("unreadable-selection-blocks-entry-before-context",!call_count&&value32(OWNER_A+0x154)==0);
    reset();failed_pc=0x8170BD0;enter();
    CHECK("context-getter-failure-has-no-toggle-or-confirm",call_count==1&&calls[0].pc==0x8170BD0&&value32(OWNER_A+0x154)==0);
    reset();getter_zero=1;enter();
    CHECK("null-native-context-has-no-button3-dispatch",call_count==1&&value32(OWNER_A+0x154)==0);
    reset();failed_pc=0x81C0820;enter();
    CHECK("button-context-failure-has-no-toggle-or-confirm",call_count==2&&value32(OWNER_A+0x154)==0);
    reset();failed_pc=0x8373750;enter();
    CHECK("native-compare-failure-has-no-fallback",call_count==3&&entry_calls(0,OWNER_A)&&value32(OWNER_A+0x154)==0&&g_compare_owner==OWNER_A);
    CHECK("native-compare-failure-reports-incomplete",strstr(last_log,"incomplete")!=NULL);
    native_ui_compare_set(0);tick();
    CHECK("failed-entry-release-needs-no-restoration",call_count==3&&!g_compare_owner&&value32(OWNER_A+0x154)==0);
    reset();compare_updates=0;enter();
    CHECK("native-compare-no-change-does-not-use-fallback",call_count==3&&entry_calls(0,OWNER_A)&&value32(OWNER_A+0x154)==0&&strstr(last_log,"incomplete"));
    compare_updates=1;tick();
    CHECK("failed-compare-can-retry-next-held-frame",call_count==6&&entry_calls(3,OWNER_A)&&value32(OWNER_A+0x154)==1);
    reset();enter();failed_pc=0x81FC220;native_ui_compare_set(0);tick();
    CHECK("native-restore-failure-keeps-owner-for-retry",restore_call(3,OWNER_A,0)&&g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==1&&strstr(last_log,"incomplete"));
    failed_pc=0;tick();
    CHECK("native-restore-retry-uses-only-model-setter",restore_call(4,OWNER_A,0)&&!g_compare_owner&&value32(OWNER_A+0x154)==0);
    reset();enter();restore_updates=0;native_ui_compare_set(0);tick();
    CHECK("native-restore-no-change-keeps-owner",restore_call(3,OWNER_A,0)&&g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==1);
    restore_updates=1;tick();
    CHECK("native-restore-no-change-recovers-next-frame",restore_call(4,OWNER_A,0)&&!g_compare_owner&&value32(OWNER_A+0x154)==0);
    reset();enter();fail_readback=1;native_ui_compare_set(0);tick();
    CHECK("restore-readback-failure-does-not-claim-completion",restore_call(3,OWNER_A,0)&&g_compare_owner==OWNER_A&&value32(OWNER_A+0x154)==0);
    failed_read32=0;fail_readback=0;tick();
    CHECK("restored-mode-observation-clears-owner-without-extra-call",call_count==4&&!g_compare_owner);
}
int main(void) {
    test_hover();test_compare_lifecycle();test_release_selection_boundary();
    test_context_and_owner_isolation();test_entry_rejection_and_engine_failures();
    CHECK("all-native-calls-use-expected-abi-without-accept-equip-confirm",!abi_errors&&!unexpected_calls);
    printf("%u item hover/compare checks; %u failures\n",checks,failures);
    return failures?1:0;
}
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--cc", default=COMPILER)
    arguments = parser.parse_args()
    output = arguments.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_bytes = SOURCE.read_bytes()
    source = source_bytes.decode("utf-8")
    extracted = {name: function(source, name) for name in FUNCTIONS}
    generated = output / "item_hover_compare.c"
    executable = output / "item_hover_compare.exe"
    generated.write_text(PRELUDE + "\n".join(extracted.values()) + CASES, encoding="utf-8")
    command = [arguments.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(generated), "-o", str(executable)]
    compiled = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": __doc__,
        "source": str(SOURCE),
        "source_sha256": digest(source_bytes),
        "functions_sha256": {name: digest(body.encode("utf-8")) for name, body in extracted.items()},
        "test_sha256": digest(Path(__file__).read_bytes()),
        "extractor_sha256": digest(inspect.getsource(function).encode("utf-8")),
        "generated_c": str(generated),
        "generated_c_sha256": digest(generated.read_bytes()),
        "compile": {"command": command, "returncode": compiled.returncode, "stdout": compiled.stdout, "stderr": compiled.stderr},
        "boundaries": [
            "ui_item_context stubs existing focus/modal/service guards; their implementation is not retested.",
            "Only native_ui_compare_set, ui_item_hover and ui_compare_tick are extracted; world_ui page-close cleanup is outside this suite.",
            "Native guest callbacks and model changes are bounded stubs; passing tests do not prove visible comparison content in the game.",
            "This suite consumes the current 0076+0077 draft C helpers, not the frozen 0076 candidate binary or 0075 replay.",
        ],
    }
    returncode = compiled.returncode
    if returncode == 0:
        execution = subprocess.run([str(executable)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        report["run"] = {"command": [str(executable)], "returncode": execution.returncode, "stdout": execution.stdout, "stderr": execution.stderr}
        report["checks"] = [{"name": line.split(" ", 1)[1], "passed": line.startswith("PASS ")} for line in execution.stdout.splitlines() if line.startswith(("PASS ", "FAIL "))]
        report["check_count"] = len(report["checks"])
        report["failures"] = [entry["name"] for entry in report["checks"] if not entry["passed"]]
        print(execution.stdout, end="")
        if execution.stderr:
            print(execution.stderr, file=sys.stderr, end="")
        returncode = execution.returncode
    elif compiled.stderr:
        print(compiled.stderr, file=sys.stderr, end="")
    final_source_bytes = SOURCE.read_bytes()
    report["source_unchanged"] = digest(final_source_bytes) == report["source_sha256"]
    final_source = final_source_bytes.decode("utf-8")
    report["tested_functions_unchanged"] = all(function(final_source, name) == body for name, body in extracted.items())
    if not report["tested_functions_unchanged"]:
        returncode = returncode or 2
    report["returncode"] = returncode
    report_path = output / "result.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {report_path}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
