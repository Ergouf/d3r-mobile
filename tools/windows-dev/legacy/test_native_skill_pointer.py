"""Exercise digit routing and the native loadout/aim action builder without a running game."""
from pathlib import Path
import subprocess

from test_hover_wheel import function

ROOT = Path(__file__).resolve().parents[2]
WORLD = ROOT / "reference/ScarletNX-src/src/nx/runtime/native_world.c"
BACKEND = ROOT / "reference/ScarletNX-src/src/nx/runtime/platform/backend/sdl3.c"
OUTPUT = ROOT / "out/windows/kbm/session/skill-pointer-tests"

PRELUDE = r'''
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef int SDL_Scancode;
typedef unsigned SDL_Keymod;
typedef struct { int unused; } CPU;
typedef struct { u64 x0; } GuestResult;
typedef struct { float x,y,z; u32 place; } WorldPos;
typedef struct { int attack;u32 handle,controller; } WalkGoal;
enum { SDL_SCANCODE_1=30,SDL_SCANCODE_4=33,SDL_KMOD_CTRL=0xc0,SDL_KMOD_ALT=0x300,SDL_KMOD_GUI=0xc00 };
#define NATIVE_POINTER_SKILL 2u
#define NATIVE_POINTER_SLOT(slot) ((u64)(slot)<<8)
#define ENTITY_STRIDE 0x360u
#define PATH_ACTOR_PC 0x866D5C0ull
#define PATH_POS_PC 0x866D580ull
#define ACTION_PC 0x80CBA30ull
#define LOG(...) do{if(0)printf(__VA_ARGS__);}while(0)
static unsigned char memory[0x40000];
#define GP(address) (memory+(address))
static u64 g_stack_top=0x30000;
static float g_mouse_x=300,g_mouse_y=200,pointer_x,pointer_y;
static unsigned pointer_slot,last_slot;
static int blocked,pointer_calls,mouse_reads,loadout_reads,actions,path_type,action_return=1,expired,alive=1,fail_loadout,fail_path;
static u32 power;
static WorldPos action_position;
static u32 action_controller;
static int native_world_ui_blocked(void){return blocked;}
static unsigned SDL_GetMouseState(float* horizontal,float* vertical){*horizontal=480;*vertical=270;mouse_reads++;return 0;}
static int pc_world_pointer(float horizontal,float vertical,u64 flags){
 pointer_calls++;pointer_x=horizontal;pointer_y=vertical;pointer_slot=(unsigned)(flags>>8);return 1;
}
static int read32(u64 address,u32* value){if(!address||address+4>sizeof memory)return 0;memcpy(value,GP(address),4);return 1;}
static int lookup(u64 table,u32 handle,unsigned stride,u64* result){
 (void)table;(void)stride;if(expired||handle!=123)return 0;*result=0x4000;return 1;
}
static int actor_alive(const CPU* cpu,u64 entity){(void)cpu;(void)entity;return alive;}
static int guest_call(const CPU* cpu,u64 pc,const u64* args,unsigned count,const float* floats,unsigned float_count,GuestResult* result){
 (void)cpu;(void)count;(void)floats;(void)float_count;
 if(pc==0x8525ED0){if(fail_loadout)return 0;last_slot=(unsigned)args[1];loadout_reads++;result->x0=0x1000+args[1]*16;return 1;}
 if(pc==PATH_ACTOR_PC){if(fail_path)return 0;path_type=1;u32 type=1,handle=(u32)args[1];memcpy(GP(args[0]),&type,4);memcpy(GP(args[0]+4),&handle,4);return 1;}
 if(pc==PATH_POS_PC){if(fail_path)return 0;path_type=2;memcpy(&action_position,GP(args[1]),sizeof action_position);return 1;}
 if(pc==ACTION_PC){u32 words[5];memcpy(words,GP(args[1]),sizeof words);power=words[1];action_controller=words[0];actions++;result->x0=action_return;return 1;}
 return 0;
}
'''

CASES = r'''
static int checks,failures;
#define CHECK(name,condition) do{checks++;if(!(condition)){printf("FAIL %s\n",name);failures++;}}while(0)
static void reset(void){
 memset(memory,0,sizeof memory);blocked=pointer_calls=mouse_reads=loadout_reads=actions=path_type=expired=fail_loadout=fail_path=0;
 action_return=alive=1;g_mouse_x=300;g_mouse_y=200;power=0;action_controller=0;last_slot=99;
 const u32 loadout[]={285903,353492,291804,243853,342281,239137};
 for(unsigned index=0;index<6;index++)memcpy(GP(0x1000+index*16),&loadout[index],4);
 u32 type=1;memcpy(GP(0x414c),&type,4);
}
int main(void){
 WorldPos position={10,20,4,42},ground={100,200,0,42};WalkGoal target={1,123,456};
 reset();for(int scancode=SDL_SCANCODE_1;scancode<=SDL_SCANCODE_4;scancode++){
  CHECK("digit-routes-to-actual-slot",pc_skill_digit(scancode,0,0)==1&&pointer_slot==(unsigned)(scancode-SDL_SCANCODE_1+2));
  CHECK("digit-keeps-pointer",pointer_x==300&&pointer_y==200);
 }
 reset();blocked=1;CHECK("menu-keeps-digit",!pc_skill_digit(SDL_SCANCODE_1,0,0)&&!pointer_calls);
 reset();CHECK("digit-repeat-consumed",pc_skill_digit(SDL_SCANCODE_1,1,0)&&!pointer_calls);
 reset();CHECK("ctrl-digit-does-not-cast",pc_skill_digit(SDL_SCANCODE_1,0,SDL_KMOD_CTRL)&&!pointer_calls);
 reset();CHECK("alt-digit-does-not-cast",pc_skill_digit(SDL_SCANCODE_1,0,SDL_KMOD_ALT)&&!pointer_calls);
 reset();CHECK("unrelated-key-not-consumed",!pc_skill_digit(40,0,0)&&!pointer_calls);
 reset();g_mouse_x=g_mouse_y=-1;CHECK("first-digit-reads-current-pointer",pc_skill_digit(SDL_SCANCODE_1,0,0)&&mouse_reads==1&&pointer_x==480&&pointer_y==270);
 const u32 powers[]={291804,243853,342281,239137};
 for(unsigned slot=2;slot<6;slot++){
  reset();CHECK("cast-resolves-live-loadout",submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,0,1,slot)&&last_slot==slot&&power==powers[slot-2]);
  CHECK("ground-cast-keeps-aim-and-place",path_type==2&&action_position.x==100&&action_position.y==200&&action_position.place==42&&fabsf(action_position.z-8.37f)<0.0001f&&action_controller==UINT32_MAX);
 }
 reset();CHECK("live-monster-uses-actor-path",submit_mouse_skill(NULL,0x9000,&position,&ground,0,&target,1,1,5)&&path_type==1&&action_controller==456);
 reset();expired=1;CHECK("expired-target-falls-back-to-ground",submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,1,1,5)&&path_type==2&&action_controller==UINT32_MAX);
 reset();alive=0;CHECK("dead-target-falls-back-to-ground",submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,1,1,5)&&path_type==2);
 reset();CHECK("no-aim-does-not-submit",!submit_mouse_skill(NULL,0x9000,&position,&ground,0,&target,0,1,5)&&!actions);
 reset();u32 empty=UINT32_MAX;memcpy(GP(0x1020),&empty,4);
 CHECK("empty-slot-has-no-fallback-power",!submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,0,1,2)&&!actions);
 reset();CHECK("invalid-slot-rejected-before-read",!submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,0,1,6)&&!loadout_reads&&!actions);
 reset();fail_loadout=1;CHECK("loadout-query-failure-stops-cast",!submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,0,1,2)&&!actions);
 reset();fail_path=1;CHECK("path-failure-stops-cast",!submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,0,1,2)&&!actions);
 reset();action_return=0;CHECK("engine-rejection-propagates",!submit_mouse_skill(NULL,0x9000,&position,&ground,1,&target,0,1,2)&&actions==1);
 printf("%d skill pointer checks; %d failures\n",checks,failures);return failures?1:0;
}
'''


def main() -> int:
    backend = BACKEND.read_text(encoding="utf-8")
    world = WORLD.read_text(encoding="utf-8")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    generated, executable = OUTPUT / "skill.c", OUTPUT / "skill.exe"
    generated.write_text(PRELUDE + function(backend, "pc_skill_digit") + function(world, "submit_mouse_skill") + CASES, encoding="utf-8")
    subprocess.run([
        "D:/workspace/msys2/msys64/clang64/bin/clang.exe", "-std=c11", "-Wall", "-Wextra", "-Werror",
        str(generated), "-o", str(executable),
    ], check=True)
    return subprocess.run([str(executable)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
