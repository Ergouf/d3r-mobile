"""Compile the production door fallback with guest-memory stubs and exercise its gates."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference/ScarletNX-src/src/nx/runtime/native_world.c"

PRELUDE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <float.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef int32_t i32;
typedef struct { int unused; } CPU;
typedef struct { float x,y,z; u32 place; } WorldPos;
typedef struct { float origin[3],direction[3],length; } WorldRay;
typedef struct { u64 x0; } GuestResult;
#define ENTITY_STRIDE 0x360
#define CAP_POWER_PC 0x84D8790
#define ASSIST_ACTION 0x45CCF
#define LOG(...) ((void)0)
static unsigned char memory[0x10000];
#define GP(a) (memory+(a))
static int cap_ok=1;
static u32 cap_value=30021;
static int readable(u64 a,size_t n) { return a<sizeof memory && n<=sizeof memory-a; }
static int read32(u64 a,u32* v) { if(!readable(a,4))return 0;memcpy(v,GP(a),4);return 1; }
static int read64(u64 a,u64* v) { if(!readable(a,8))return 0;memcpy(v,GP(a),8);return 1; }
static void w32(u64 a,u32 v) { memcpy(GP(a),&v,4); }
static void w64(u64 a,u64 v) { memcpy(GP(a),&v,8); }
static void wf(u64 a,float v) { memcpy(GP(a),&v,4); }
static int project_point(const CPU* c,u32 place,float x,float y,float z,float out[2]) {
    (void)c;(void)place;(void)x;(void)y;out[0]=100;out[1]=100-z*10;return 1;
}
static int guest_call(const CPU* c,u64 pc,const u64* a,unsigned n,const float* f,unsigned nf,GuestResult* r) {
    (void)c;(void)pc;(void)a;(void)n;(void)f;(void)nf;r->x0=cap_value;return cap_ok;
}
'''

CASES = r'''
static WorldRay ray;
static WorldPos pos;
static int pixel[2],ground_ok;
static float occlusion;
static void reset(void) {
    memset(memory,0,sizeof memory);
    w32(0x100+0x100,1);w32(0x100+0x168,0);w64(0x100+0x120,0x400);w64(0x400,0x800);
    w32(0x800,0x77000000);w32(0x800+0x14,0x78000001);w32(0x800+0x18,178293);
    w32(0x800+0xa0,42);wf(0x800+0x60,40);wf(0x800+0x90,0);
    pos=(WorldPos){0,0,0,42};ray=(WorldRay){{-60,0,0},{1,0,0},200};
    pixel[0]=110;pixel[1]=90;ground_ok=1;occlusion=120;cap_ok=1;cap_value=30021;
}
static int check(const char* name,int expected) {
    WorldPos found={0};u32 handle=0,controller=0,power=0,sno=0;
    int got=door_candidate_near(NULL,0x100,&pos,&ray,occlusion,ground_ok,pixel,
                               &found,&handle,&controller,&power,&sno);
    int pass=got==expected;
    u32 expected_sno;read32(0x800+0x18,&expected_sno);
    if(got)pass=pass&&handle==0x77000000&&controller==0x78000001&&power==30021&&
        sno==expected_sno&&found.place==42&&found.x==40;
    printf("%s %s\n",pass?"PASS":"FAIL",name);return !pass;
}
int main(void) {
    int failed=0;
    reset();failed+=check("visible-zero-radius-door",1);
    reset();occlusion=98;failed+=check("depth-tolerance-boundary",1);
    reset();occlusion=50;failed+=check("terrain-in-front-of-door",0);
    reset();ground_ok=0;failed+=check("ground-query-failed",0);
    reset();occlusion=FLT_MAX;failed+=check("ground-sentinel",0);
    reset();occlusion=NAN;failed+=check("ground-nan",0);
    reset();occlusion=INFINITY;failed+=check("ground-infinity",0);
    reset();occlusion=-1;failed+=check("ground-negative",0);
    reset();ray.origin[0]=50;failed+=check("door-behind-camera",0);
    reset();ray.length=99;failed+=check("door-beyond-ray",0);
    reset();ray.length=NAN;failed+=check("invalid-ray-length",0);
    reset();wf(0x800+0x60,NAN);failed+=check("invalid-door-position",0);
    reset();w32(0x800+0x18,130400);failed+=check("stash-not-in-door-allowlist",0);
    reset();w32(0x800+0xa0,43);failed+=check("different-place",0);
    reset();w32(0x800,0x77000001);failed+=check("stale-table-slot",0);
    reset();wf(0x800+0x90,-1);failed+=check("negative-radius",0);
    reset();wf(0x800+0x90,NAN);failed+=check("invalid-radius",0);
    reset();cap_ok=0;failed+=check("capability-call-failed",0);
    reset();cap_value=0;failed+=check("no-operate-power",0);
    reset();cap_value=ASSIST_ACTION;failed+=check("assist-power-rejected",0);
    reset();pixel[0]=125;failed+=check("outside-screen-radius",0);
    reset();pos.x=-81;failed+=check("outside-world-distance",0);
    reset();w32(0x800+0x18,191492);failed+=check("hearth-portal-zero-radius",1);
    reset();w32(0x800+0x18,196657);failed+=check("town-portal-zero-radius",1);
    reset();w32(0x800+0x18,176002);failed+=check("blue-arch-portal",1);
    reset();w32(0x800+0x18,176001);failed+=check("orange-arch-portal",1);
    reset();w32(0x800+0x18,191492);occlusion=50;failed+=check("occluded-hearth-portal",0);
    reset();wf(0x800+0x8c,8);pixel[1]=25;failed+=check("authored-height-portal-hit",1);
    reset();wf(0x800+0x8c,NAN);failed+=check("invalid-height",0);
    reset();wf(0x800+0x8c,-1);failed+=check("negative-height",0);
    return failed?1:0;
}
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cc", default="D:/workspace/msys2/msys64/clang64/bin/clang.exe")
    ap.add_argument("--out", type=Path, default=ROOT / "out/windows/kbm/session/door-fallback-tests")
    args = ap.parse_args()
    source = SOURCE.read_text("utf-8")
    start = source.index("static int door_sno(")
    end = source.index("static void world_tick(", start)
    args.out.mkdir(parents=True, exist_ok=True)
    c_path, exe_path = args.out / "door-fallback.c", args.out / "door-fallback.exe"
    portal_start = source.index("static int portal_sno(")
    portal_end = source.index("static int walk_into_sno(", portal_start)
    c_path.write_text(PRELUDE + source[portal_start:portal_end] + source[start:end] + CASES, "utf-8")
    built = subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c_path),
                            "-o", str(exe_path)], capture_output=True, text=True)
    if built.returncode:
        print(built.stderr)
        return built.returncode
    run = subprocess.run([str(exe_path)], capture_output=True, text=True)
    print(run.stdout, end="")
    (args.out / "result.json").write_text(json.dumps({
        "source": str(SOURCE), "scope": "production candidate function with guest-memory stubs; no live-game claim",
        "returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr,
    }, indent=2), "utf-8")
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
