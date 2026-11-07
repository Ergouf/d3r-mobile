"""Exercise the production map picker: act-local indices and modal/clip guards."""
from pathlib import Path
import subprocess
from kbm_source import function, read_runtime

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'reference/ScarletNX-src/src/nx/runtime/native_world.c'
OUT = ROOT / 'out/windows/kbm/session/map-picker-tests'
PRELUDE = r'''
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <float.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
typedef struct { int unused; } CPU;
typedef struct { u64 x0; } GuestResult;
typedef struct { const CPU* cpu; u64 map; float point[2]; } UiPick;
static unsigned char memory[0x9200000];
static u64 keys[16], focus=UINT64_MAX;
static int details=-1,changed_tab=-1,dirty,calls,clip=1,chapter=-1;
#define GP(a) (memory+(a))
#define LOG(...) do{if(0)printf(__VA_ARGS__);}while(0)
static int kbm_readable(u64 a,size_t n){return a&&a<sizeof memory&&n<=sizeof memory-a;}
static int kbm_read64(u64 a,u64* v){if(!kbm_readable(a,8))return 0;memcpy(v,GP(a),8);return 1;}
static int kbm_read32(u64 a,u32* v){if(!kbm_readable(a,4))return 0;memcpy(v,GP(a),4);return 1;}
static void w64(u64 a,u64 v){memcpy(GP(a),&v,8);}
static void w32(u64 a,u32 v){memcpy(GP(a),&v,4);}
static void wf(u64 a,float v){memcpy(GP(a),&v,4);}
static u64 ui_object(u64 m,u64 k){(void)m;for(int i=1;i<16;i++)if(keys[i]==k)return i*0x1000;return 0;}
static int ui_visible(u64 m,u64 o){(void)m;u32 f;return kbm_read32(o+0x18,&f)&&(f&4);}
static int ui_within(u64 m,u64 o,u64 root){(void)m;return (root==0x8000&&o!=0x9000)||(o==root)||(root==0x2000&&(o==0x3000||o==0x4000));}
static int ui_code(u64 pc){return pc>=0x8000000&&pc<0x9000000;}
static int ui_inside(UiPick* p,u64 o){float r[4];memcpy(r,GP(o+0x88),16);return clip&&p->point[0]>=r[0]&&p->point[0]<r[2]&&p->point[1]>=r[1]&&p->point[1]<r[3];}
static int guest_call(const CPU* c,u64 pc,const u64* a,unsigned n,const float* f,unsigned nf,GuestResult* r){
 (void)c;(void)n;(void)f;(void)nf;
 if(pc==0x832D180){w64(0x70000,focus);r->x0=0x70000;return 1;}
 if(pc==0x800F9F0){r->x0=999;return 1;}
 if(pc==0x823EF60){details=(int)a[0];calls++;return 1;}
 if(pc==0x8170BD0){r->x0=0x71000;return 1;}
 if(pc==0x81C0B80){dirty++;return 1;}
 if(pc==0x816F550){changed_tab=(int)a[1];calls++;return 1;}
 if(pc==0x823EB50){u32 selected;kbm_read32(0x20044,&selected);kbm_read32(0x21000+selected*24+8,&selected);chapter=(int)selected;calls++;return 1;}
 return 0;
}
'''
CASES = r'''
static void reset(unsigned first){
 memset(memory,0,sizeof memory);memset(keys,0,sizeof keys);focus=UINT64_MAX;
 details=changed_tab=chapter=-1;dirty=calls=0;clip=1;
 keys[1]=ui_path_key("root.normallayer.map_dialog_mainpage");
 keys[2]=ui_path_key("root.normallayer.waypointmap_main");
 keys[3]=100;keys[4]=101;keys[5]=200;
 w32(0x2018,4);w32(0x3018,4);w32(0x4018,4);w32(0x5018,4);
 keys[8]=1;w32(0x8018,4);
 w64(0x914F840,0x60000);w64(0x60010,0x61000);w64(0x61b80,0x62000);w64(0x62000,1);
 w64(0x62010,0x63000);w64(0x63000,0x64000);w32(0x63008,1);w64(0x64000,0x2000);
 w64(0x2000,0x66000);w64(0x660b0,0x83B81F0);w64(0x2118,0x65000);
 w64(0x9154E30,0x20000);w64(0x20028,0x21000);w64(0x20030,2);w32(0x20044,0);
 for(unsigned i=0;i<2;i++){
  u64 row=0x21000+i*24,obj=0x3000+i*0x1000;
  wf(row,300+i*150);wf(row+4,300);w32(row+8,first+i);w64(row+16,100+i);w64(obj,0x90AF208);
  wf(obj+0x88,270+i*150);wf(obj+0x8c,270);wf(obj+0x90,330+i*150);wf(obj+0x94,330);
 }
 w64(0x9152080,0x22000);w64(0x22000,0x23000);w64(0x23040,0x24000);w64(0x23108,0x24000);
 w64(0x24000,0x25000);w64(0x24008,3);w32(0x2401c,0);
 const u64 opens[]={0x83EC6C0,0x823E1E0,0x823E7A0},closes[]={0x83EC8E0,0x823E760,0x823E9D0};
 for(unsigned i=0;i<3;i++){w64(0x25000+i*24,opens[i]);w64(0x25008+i*24,closes[i]);w32(0x25010+i*24,1);}
}
static void world_map(void){
 keys[6]=ui_path_key("root.normallayer.waypointmap_main.layoutroot.navigation.map.worldtab");
 keys[7]=ui_path_key("root.normallayer.waypointmap_main.layoutroot.overlaycontainer.worldmap");
 w32(0x6018,4);w32(0x7018,4);w64(0x20030,5);
 wf(0x7088,0);wf(0x708c,80);wf(0x7090,960);wf(0x7094,600);
 for(unsigned index=0;index<5;index++){
  u64 row=0x21000+index*24;
  wf(row,200+index*100);wf(row+4,300);w32(row+8,400-index*100);w64(row+16,1);
 }
}
static int failures,checks;
#define CHECK(name,expr) do{checks++;if(!(expr)){printf("FAIL %s\n",name);failures++;}}while(0)
int main(void){
 UiPick p={NULL,1,{450,300}};u32 selected;
 reset(0);CHECK("act-one-node",ui_map_click(&p,1)==1&&details==1&&calls==1&&dirty==1);
 CHECK("selected-local-index",kbm_read32(0x20044,&selected)&&selected==1);
 reset(58);CHECK("act-five-global-id",ui_map_click(&p,2)==1&&details==1&&calls==1);
 CHECK("act-five-local-index",kbm_read32(0x20044,&selected)&&selected==1);
 CHECK("focus-unchanged",focus==UINT64_MAX);
 reset(58);focus=200;CHECK("foreign-modal",ui_map_click(&p,3)==0&&!calls);
 reset(58);clip=0;CHECK("clipped-node",ui_map_click(&p,4)==0&&!calls);
 reset(58);w32(0x4018,0);CHECK("hidden-node",ui_map_click(&p,5)==0&&!calls);
 reset(58);w64(0x4000,0x90AF200);CHECK("wrong-node-class",ui_map_click(&p,6)==0&&!calls);
 reset(58);w32(0x21020,256);CHECK("invalid-waypoint-id",ui_map_click(&p,7)==0&&!calls);
 reset(58);w64(0x20030,257);CHECK("invalid-table-length",ui_map_click(&p,8)==0&&!calls);
 reset(58);w32(0x20020,1);CHECK("other-player",ui_map_click(&p,9)==0&&!calls);
 reset(58);p.point[0]=900;CHECK("empty-space",ui_map_click(&p,10)==0&&!calls);
 reset(58);p.point[0]=700;p.point[1]=51;CHECK("world-tab",ui_map_click(&p,11)==1&&changed_tab==2);
 reset(58);w32(0x25040,0);CHECK("disabled-tab",ui_map_click(&p,12)==1&&!calls);
 reset(58);w64(0x25038,0);CHECK("wrong-tab-callback",ui_map_click(&p,13)==0&&!calls);
 reset(58);w32(0x2018,0);CHECK("closed-map",ui_map_click(&p,14)==0&&!calls);
 reset(58);focus=200;w32(0x5018,0);CHECK("hidden-stale-focus-tab",ui_map_click(&p,24)==1&&changed_tab==2);
 reset(58);w32(0x63008,0);CHECK("unsubscribed-map",ui_map_click(&p,25)==0&&!calls);
 reset(58);w64(0x62000,2);CHECK("registry-changed",ui_map_click(&p,26)==0&&!calls);
 reset(58);w32(0x63008,2);w64(0x64008,0x9000);w32(0x9018,4);CHECK("overlay-without-focus",ui_map_click(&p,27)==0&&!calls);
 reset(58);w32(0x63008,2);w64(0x64008,0xa000);w32(0xa018,4);w64(0xa000,0x66000);w64(0xa118,0x67000);w64(0x67020,0x8387180);CHECK("other-page-input-owner",ui_map_click(&p,28)==0&&!calls);
 reset(58);w32(0x63008,2);w64(0x64008,0x9000);CHECK("hidden-overlay",ui_map_click(&p,29)==1&&changed_tab==2);
 reset(58);world_map();p.point[0]=200;p.point[1]=300;CHECK("world-act-five-id-400",ui_map_click(&p,15)==1&&chapter==400&&calls==1&&details==-1);
 reset(58);world_map();p.point[0]=600;CHECK("world-act-one-id-zero",ui_map_click(&p,16)==1&&chapter==0&&calls==1&&details==-1);
 reset(58);world_map();focus=200;CHECK("world-modal-guard",ui_map_click(&p,17)==0&&!calls);
 reset(58);world_map();clip=0;CHECK("world-clip-guard",ui_map_click(&p,18)==0&&!calls);
 reset(58);world_map();w32(0x21008,401);CHECK("world-invalid-chapter",ui_map_click(&p,19)==0&&!calls);
 reset(58);world_map();w32(0x21020,400);CHECK("world-duplicate-chapter",ui_map_click(&p,20)==0&&!calls);
 reset(58);world_map();w64(0x20030,4);CHECK("world-invalid-count",ui_map_click(&p,21)==0&&!calls);
 reset(58);world_map();p.point[0]=900;CHECK("world-empty-space",ui_map_click(&p,22)==0&&!calls);
 reset(58);world_map();w32(0x6018,0);p.point[0]=200;CHECK("hidden-world-tab",ui_map_click(&p,23)==0&&!calls);
 printf("%d map picker checks; %d failures\n",checks,failures);return failures?1:0;
}
'''

def main():
    source=read_runtime()
    OUT.mkdir(parents=True,exist_ok=True)
    c=OUT/'map.c'; exe=OUT/'map.exe'
    c.write_text(PRELUDE+function(source,'ui_path_key')+function(source,'ui_pointer_page_allowed')+function(source,'ui_map_click')+CASES,encoding='utf-8')
    subprocess.run(['D:/workspace/msys2/msys64/clang64/bin/clang.exe','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(c),'-o',str(exe)],check=True)
    return subprocess.run([str(exe)]).returncode

if __name__=='__main__':raise SystemExit(main())
