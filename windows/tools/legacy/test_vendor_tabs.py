"""Exercise the production service-tab selector with guest-memory and UI stubs."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "windows/source/ScarletNX-src/src/nx/runtime/native_world.c"

PRELUDE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { int unused; } CPU;
typedef struct { u64 x0; } GuestResult;
typedef struct { const CPU* cpu; u64 map; float point[2]; } UiPick;
typedef struct { u64 obj,parent; } UiChild;
static UiChild g_ui_children[8];
static u32 g_ui_child_count;
static unsigned char memory[0x9200000];
static u64 parents[32],keys[32];
static int clip_ok,focus_ok,selected_calls;
static u64 selected_args[4];
#define GP(a) (memory+(a))
#define LOG(...) do { if(0)printf(__VA_ARGS__); } while(0)
static int readable(u64 a,size_t n){return a && a<sizeof memory && n<=sizeof memory-a;}
static int read32(u64 a,u32* v){if(!readable(a,4))return 0;memcpy(v,GP(a),4);return 1;}
static int read64(u64 a,u64* v){if(!readable(a,8))return 0;memcpy(v,GP(a),8);return 1;}
static void w32(u64 a,u32 v){memcpy(GP(a),&v,4);}
static void w64(u64 a,u64 v){memcpy(GP(a),&v,8);}
static void wf(u64 a,float v){memcpy(GP(a),&v,4);}
static u64 ui_object(u64 map,u64 key){(void)map;for(int i=1;i<32;i++)if(keys[i]==key)return i*0x1000;return 0;}
static u64 ui_parent(u64 map,u64 obj){(void)map;return obj<0x20000?parents[obj/0x1000]:0;}
static int ui_visible(u64 map,u64 obj){for(int i=0;obj&&i<64;i++,obj=ui_parent(map,obj)){u32 flags;if(!read32(obj+0x18,&flags)||!(flags&4))return 0;if(!ui_parent(map,obj))return 1;}return 0;}
static int ui_inside(UiPick* p,u64 obj){(void)p;(void)obj;return clip_ok;}
static int ui_code(u64 pc){return pc>=0x8005000&&pc<0x8c78000&&!(pc&3);}
static int guest_call(const CPU* c,u64 pc,const u64* a,unsigned n,const float* f,unsigned nf,GuestResult* r){
 (void)c;(void)f;(void)nf;
 if(pc==0x832D180){if(r)r->x0=0x15000;return focus_ok;}
 if(pc==0x816F550&&n==4){selected_calls++;memcpy(selected_args,a,sizeof selected_args);return 1;}
 return 0;
}
'''

CASES = r'''
static UiPick pick;
static u32 sub_count;
static u32 expected_group;
static void reset(void){
 memset(memory,0,sizeof memory);memset(parents,0,sizeof parents);memset(keys,0,sizeof keys);
 memset(g_ui_children,0,sizeof g_ui_children);selected_calls=0;memset(selected_args,0,sizeof selected_args);
 clip_ok=focus_ok=1;sub_count=1;expected_group=2;pick=(UiPick){NULL,1,{381,51}};
 w64(0x9152080,0x1000);w64(0x1000,0x1100);w64(0x1110,0x2000);w64(0x1208,0x2000);
 w64(0x2000,0x3000);w64(0x2008,4);w32(0x2018,0);w32(0x201c,0);
 const u64 cb[]={0x837DF30,0x837DF60,0x837DF90,0x837DFC0};
 for(int i=0;i<4;i++){w64(0x3000+i*0x18,cb[i]);w32(0x3010+i*0x18,i<2);}
 w64(0x9158028,0x4000);w64(0x4000,0x4100);w64(0x4100,0x90AB418);w32(0x4118,1);w32(0x4300,1);
 keys[5]=ui_path_key("root.normallayer.consoleinventoryring_main");
 keys[6]=ui_path_key("root.normallayer.consoleinventoryring_main.layoutroot");
 /* The runtime's layer roots are reserved IDs, not FNV hashes. */
 keys[14]=3;keys[22]=1;w32(0x16018,4);
 parents[5]=0x16000;parents[6]=0x5000;parents[7]=0x6000;
 const float left[]={126,303,505,682,714};
 for(int i=0;i<5;i++){
  u64 obj=0x8000+i*0x1000;
  if(i==4)obj=0xf000;
  parents[obj/0x1000]=0x7000;w64(obj,0x90ABB48);
  wf(obj+0x88,left[i]);wf(obj+0x8c,39);wf(obj+0x90,left[i]+156);wf(obj+0x94,63);
  g_ui_children[i]=(UiChild){obj,0x7000};
 }
 for(int i=5;i<16;i++)w32(i*0x1000+0x18,4);
 g_ui_child_count=5;
 w64(0x6000,0x12000);w64(0x120b0,0x83B81F0);w64(0x6118,0x13000);w64(0x13020,0x81FB910);
 w64(0x14000,0x6000);w64(0x15000,UINT64_MAX);
}
static void reset_smith(void){
 reset();expected_group=5;w64(0x1110,0);w64(0x1128,0x2000);w64(0x2008,5);
 w64(0x91598B0,0x4000);w64(0x4100,0x90AFC60);w32(0x4300,0);
 const u64 cb[]={0x8419140,0x8419170,0x84191A0,0x84191D0,0x8419200};
 for(int i=0;i<5;i++){
  w64(0x3000+i*0x18,cb[i]);w64(0x3008+i*0x18,0);w32(0x3010+i*0x18,1);
  u64 obj=g_ui_children[i].obj;wf(obj+0x88,90+156*i);wf(obj+0x90,246+156*i);
 }
 pick.point[0]=324;
}
static void reset_jeweler(void){
 reset();expected_group=6;w64(0x1110,0);w64(0x1130,0x2000);w64(0x2008,4);
 w64(0x9159948,0x4000);w64(0x4100,0x90AFE78);w32(0x4300,0);
 const u64 open[4]={0x84276A0,0x84276D0,0x8427720,0x8427780};
 const u64 close[4]={0,0x8427700,0x8427750,0};
 for(int i=0;i<4;i++){w64(0x3000+i*0x18,open[i]);w64(0x3008+i*0x18,close[i]);w32(0x3010+i*0x18,1);}
 pick.point[0]=381;
}
static void reset_mystic(void){
 reset();expected_group=7;w64(0x1110,0);w64(0x1138,0x2000);w64(0x2008,4);
 w64(0x9153E68,0x4000);w64(0x4100,0x90A3750);w32(0x4300,0);
 const u64 open[4]={0x81DFB00,0x81DFB30,0x81DFB60,0x81DFB90};
 for(int i=0;i<4;i++){w64(0x3000+i*0x18,open[i]);w64(0x3008+i*0x18,0);w32(0x3010+i*0x18,1);}
 pick.point[0]=381;
}
static const float service_center[4]={204,381,583,760};
static int check(const char* name,int handled,int calls,u32 target){
 int got=ui_service_tab_click(&pick,7,0x14000,sub_count);
 int pass=got==handled&&selected_calls==calls;
 if(calls)pass=pass&&selected_args[0]==expected_group&&selected_args[1]==target&&selected_args[2]==0&&selected_args[3]==0;
 printf("%s %s\n",pass?"PASS":"FAIL",name);return !pass;
}
int main(void){
 int failed=0;
 reset();failed+=check("buy-to-sell",1,1,1);
 reset();w32(0x2018,1);w32(0x4300,0);pick.point[0]=204;failed+=check("sell-to-buy",1,1,0);
 reset();pick.point[0]=583;failed+=check("disabled-repair",1,0,0);
 reset();pick.point[0]=760;failed+=check("disabled-buyback",1,0,0);
 reset();pick.point[0]=204;failed+=check("same-tab",1,0,0);
 reset();w32(0x3010+2*0x18,1);pick.point[0]=583;failed+=check("enabled-repair",1,1,2);
 reset();w32(0x3010+3*0x18,1);pick.point[0]=760;failed+=check("enabled-buyback-overlapping-fifth-label",1,1,3);
 reset();clip_ok=0;failed+=check("clipped-label",0,0,0);
 reset();pick.point[1]=63;failed+=check("outside-label",0,0,0);
 reset();wf(0x9088,NAN);failed+=check("nan-rectangle",0,0,0);
 reset();wf(0x9090,1000);failed+=check("wrong-label-shape",0,0,0);
 reset();w32(0x9018,0);failed+=check("hidden-label",0,0,0);
 reset();w32(0x5018,0);failed+=check("hidden-page",0,0,0);
 reset();g_ui_children[1].parent=0x6000;failed+=check("mixed-tab-parents",0,0,0);
 reset();g_ui_children[5]=g_ui_children[1];g_ui_child_count=6;failed+=check("duplicate-tab",0,0,0);
 reset();g_ui_child_count=3;failed+=check("incomplete-tabbar",0,0,0);
 reset();w64(0x1208,0x5000);failed+=check("different-navigation-group",0,0,0);
 reset();w64(0x2008,5);failed+=check("wrong-group-count",0,0,0);
 reset();w32(0x201c,1);failed+=check("other-player",0,0,0);
 reset();w32(0x2018,4);failed+=check("invalid-selected-slot",0,0,0);
 reset();w32(0x4300,3);failed+=check("controller-group-disagreement",0,0,0);
/* Act 2 vendors report mode 0 instead of 1 on the buy slot; 0041 accepts
   that as an alternative, so it must still reach the callback. */
reset();w32(0x4300,0);failed+=check("act2-vendor-mode0",1,1,1);
 reset();w32(0x4118,0);failed+=check("inactive-controller",0,0,0);
 reset();w64(0x4000,0);failed+=check("missing-controller",0,0,0);
 reset();w64(0x3018,0x8200000);failed+=check("wrong-open-callback",0,0,0);
 reset();w64(0x3020,0x8200000);failed+=check("unexpected-close-callback",0,0,0);
 reset();w32(0x3028,2);failed+=check("invalid-enabled-flag",0,0,0);
 reset();sub_count=0;failed+=check("no-subscribers",0,0,0);
 reset();w64(0x14000,0);failed+=check("vendor-not-subscribed",1,0,0);
 reset();w64(0x13020,0x8200000);failed+=check("wrong-vendor-owner",1,0,0);
 reset();parents[12]=0xe000;w64(0x14008,0xc000);sub_count=2;failed+=check("top-layer-subscriber",1,0,0);
 reset();keys[14]=2;parents[12]=0xe000;w64(0x14008,0xc000);sub_count=2;failed+=check("second-overlay-layer",1,0,0);
 reset();parents[12]=0xe000;w32(0xc018,0);w64(0x14008,0xc000);sub_count=2;failed+=check("hidden-overlay-subscriber",1,1,1);
 reset();parents[12]=0x16000;w64(0x14008,0xc000);sub_count=2;failed+=check("normal-layer-global-subscriber",1,1,1);
 reset();w64(0x14008,0xc000);sub_count=2;failed+=check("unrooted-subscriber",1,0,0);
 reset();keys[22]=0;failed+=check("missing-normal-layer",1,0,0);
 reset();w32(0x16018,0);failed+=check("hidden-normal-layer",0,0,0);
 reset();parents[13]=0x16000;w64(0xd000,0x12000);w64(0xd118,0x13000);w64(0x14008,0xd000);sub_count=2;failed+=check("other-callback-owner",1,0,0);
 reset();keys[12]=123;w64(0x15000,123);failed+=check("focus-outside-page",1,0,0);
 reset();keys[12]=123;parents[12]=0x6000;w64(0x15000,123);failed+=check("focus-inside-page",1,1,1);
 reset();keys[12]=123;parents[12]=0x6000;w32(0xc018,0);w64(0x15000,123);failed+=check("hidden-focus",1,0,0);
 reset();w64(0x15000,123);failed+=check("unknown-focus",1,0,0);
 reset();focus_ok=0;failed+=check("focus-query-failed",1,0,0);
 reset();w64(0x4100,0x90AFC60);failed+=check("vendor-wrong-controller-vtable",0,0,0);
 for(u32 from=0;from<5;from++)for(u32 to=0;to<5;to++){
  char name[64];reset_smith();w32(0x2018,from);w32(0x4300,from);pick.point[0]=168+156*to;
  snprintf(name,sizeof name,"blacksmith-%u-to-%u",from,to);failed+=check(name,1,from!=to,to);
 }
 reset_smith();w32(0x4118,0);failed+=check("blacksmith-inactive",0,0,0);
 reset_smith();w64(0x4100,0x90AB418);failed+=check("blacksmith-vendor-controller-rejected",0,0,0);
 reset_smith();w32(0x4300,1);failed+=check("blacksmith-controller-group-disagreement",0,0,0);
 reset_smith();w32(0x3010+4*0x18,0);pick.point[0]=792;failed+=check("blacksmith-disabled-training",1,0,0);
 reset_smith();g_ui_child_count=4;failed+=check("blacksmith-missing-fifth-tab",0,0,0);
 reset_smith();w64(0x3000,0x837DF30);failed+=check("blacksmith-vendor-callback-rejected",0,0,0);
 reset_smith();parents[12]=0xe000;w64(0x14008,0xc000);sub_count=2;failed+=check("blacksmith-top-layer-subscriber",1,0,0);
 reset_smith();keys[12]=123;w64(0x15000,123);failed+=check("blacksmith-focus-outside-page",1,0,0);
 /* Jeweller: slots 1 and 2 carry their own close callbacks; slots 0 and 3
    must still have none, so a close callback there is a different page. */
 for(u32 from=0;from<4;from++)for(u32 to=0;to<4;to++){
  char name[64];reset_jeweler();w32(0x2018,from);w32(0x4300,from);pick.point[0]=service_center[to];
  snprintf(name,sizeof name,"jeweler-%u-to-%u",from,to);failed+=check(name,1,from!=to,to);
 }
 reset_jeweler();pick.point[0]=service_center[0];failed+=check("jeweler-current-tab",1,0,0);
 reset_jeweler();w32(0x3010+3*0x18,0);pick.point[0]=service_center[3];failed+=check("jeweler-disabled-training",1,0,0);
 reset_jeweler();w64(0x3008+1*0x18,0);failed+=check("jeweler-missing-close-callback",0,0,0);
 reset_jeweler();w64(0x3008+2*0x18,0x8427700);failed+=check("jeweler-swapped-close-callback",0,0,0);
 reset_jeweler();w64(0x3008+0*0x18,0x8427700);failed+=check("jeweler-unexpected-close-callback",0,0,0);
 reset_jeweler();w64(0x3000,0x8419140);failed+=check("jeweler-smith-callback-rejected",0,0,0);
 reset_jeweler();w64(0x4100,0x90AFC60);failed+=check("jeweler-smith-controller-rejected",0,0,0);
 reset_jeweler();w32(0x4300,1);failed+=check("jeweler-controller-mode-mismatch",0,0,0);
 reset_jeweler();w32(0x4118,0);failed+=check("jeweler-inactive-controller",0,0,0);
 /* Mystic: the controller vtable is not captured yet; everything else is
    still required to match. */
 for(u32 from=0;from<4;from++)for(u32 to=0;to<4;to++){
  char name[64];reset_mystic();w32(0x2018,from);w32(0x4300,from);pick.point[0]=service_center[to];
  snprintf(name,sizeof name,"mystic-%u-to-%u",from,to);failed+=check(name,1,from!=to,to);
 }
 reset_mystic();w64(0x3000+3*0x18,0x81DFB00);failed+=check("mystic-duplicate-callback",0,0,0);
 reset_mystic();w64(0x3008,0x8427750);failed+=check("mystic-unexpected-close-callback",0,0,0);
 reset_mystic();w32(0x2018,3);w32(0x4300,2);pick.point[0]=service_center[0];failed+=check("mystic-controller-mode-mismatch",0,0,0);
 reset_mystic();w64(0x4100,0x90AFE78);failed+=check("mystic-jeweler-controller-rejected",0,0,0);
 reset_mystic();w32(0x4118,0);failed+=check("mystic-inactive-controller",0,0,0);
 reset_mystic();w64(0x1130,0x2000);failed+=check("ambiguous-service-group",0,0,0);
 return failed?1:0;
}
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cc", default="D:/workspace/msys2/msys64/clang64/bin/clang.exe")
    ap.add_argument("--out", type=Path, default=ROOT / "out/windows/kbm/session/vendor-tab-tests")
    args = ap.parse_args()
    source = SOURCE.read_text("utf-8")
    def section(start: str, end: str) -> str:
        at = source.index(start)
        return source[at:source.index(end, at)]
    functions = section("static u64 ui_path_key(", "static int ui_tab_state(")
    functions += section("/* Service ABI whitelist", "static int ui_visit(")
    args.out.mkdir(parents=True, exist_ok=True)
    c_path, exe_path = args.out / "vendor-tabs.c", args.out / "vendor-tabs.exe"
    c_path.write_text(PRELUDE + functions + CASES, "utf-8")
    built = subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c_path),
                            "-o", str(exe_path)], capture_output=True, text=True)
    if built.returncode:
        print(built.stderr)
        return built.returncode
    run = subprocess.run([str(exe_path)], capture_output=True, text=True)
    print(run.stdout, end="")
    (args.out / "result.json").write_text(json.dumps({
        "source": str(SOURCE), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "scope": "production selector with guest-memory/UI stubs; no live-game claim",
        "returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr,
    }, indent=2), "utf-8")
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
