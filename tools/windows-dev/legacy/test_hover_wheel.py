"""Run production hover routing/selectors against bounded memory and call stubs.

These tests validate selection-only routing, modal isolation, coalescing and
click precedence. Live UI content is verified separately through SDL motion.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference/ScarletNX-src/src/nx/runtime/native_world.c"
OUT = ROOT / "out/windows/kbm/session/hover-tests"

PRELUDE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { u64 x[31],pc; } CPU;
typedef struct { float x,y; u32 width,height; u64 fallback; u32 serial,frame; } PointerPress;
typedef struct { float x,y; u32 width,height,frame; } HoverPoint;
typedef struct { u64 x0; } GuestResult;
typedef struct { const CPU* cpu; u64 map; float point[2]; int hover; } UiPick;
typedef struct { u64 group,page; u32 enabled[6]; int current; } UiTabState;
typedef struct { const char* name; u32 slot; } UiEquipSlot;
typedef int PMutex;
static PMutex g_pointer_lock;
static PointerPress g_pointer;
static PointerPress g_ui_pointers[16];
static unsigned g_ui_read,g_ui_count;
static PointerPress g_skill_pointers[8];
static unsigned g_skill_read,g_skill_count;
static int g_item_drag_active;
#define NATIVE_POINTER_SKILL 2u
#define NATIVE_POINTER_SLOT(slot) ((u64)(slot)<<8)
#define NATIVE_POINTER_UI_DOWN (1ull<<16)
#define NATIVE_POINTER_UI_UP (1ull<<17)
#define NATIVE_POINTER_UI_RIGHT (1ull<<18)
#define NATIVE_POINTER_UI_EVENTS (NATIVE_POINTER_UI_DOWN|NATIVE_POINTER_UI_UP|NATIVE_POINTER_UI_RIGHT)
static HoverPoint g_hover;
static int g_have_hover,g_have_pointer,g_cancel,g_enabled,g_ui_blocked,g_busy;
static unsigned g_world_command;
u64 g_footer_object;
static char g_footer_original[512],g_footer_display[512];
static u32 g_serial,g_frames;
static u64 g_stack_top=0x70000;
static struct {int active;} g_goal;
static unsigned char memory[0x9200000];
static u64 keys[128],parents[128];
static int page_current,page_ok,clip_ok,pixel_ok,focus_ok,fake_blocked;
static int selected_calls,unexpected_calls,click_calls,log_calls,highlight_calls,action_calls,native_actions;
static int native_action_press(u64 pad){(void)pad;native_actions++;return 1;}
static u32 action_id;
static u32 categories[32],slot_count;
static u64 focus_key;
#define GP(a) (memory+(a))
#define LOG(...) do {log_calls++;if(0)printf(__VA_ARGS__);} while(0)
#define UI_PC 0x80
static void pm_lock(PMutex* p){(void)p;}
static void pm_unlock(PMutex* p){(void)p;}
static int readable(u64 a,size_t n){return a&&a<sizeof memory&&n<=sizeof memory-a;}
static int read32(u64 a,u32* v){if(!readable(a,4))return 0;memcpy(v,GP(a),4);return 1;}
static int read64(u64 a,u64* v){if(!readable(a,8))return 0;memcpy(v,GP(a),8);return 1;}
static void w32(u64 a,u32 v){memcpy(GP(a),&v,4);}
static void w64(u64 a,u64 v){memcpy(GP(a),&v,8);}
static void wf(u64 a,float v){memcpy(GP(a),&v,4);}
static u64 ui_object(u64 m,u64 key){(void)m;for(unsigned i=1;i<128;i++)if(keys[i]==key)return i*0x1000;return 0;}
static int ui_visible(u64 m,u64 obj){(void)m;for(int i=0;obj&&i<64;i++,obj=parents[obj/0x1000]){u32 f;if(obj>=0x80000||!read32(obj+0x18,&f)||!(f&4))return 0;if(!parents[obj/0x1000])return 1;}return 0;}
static int ui_within(u64 m,u64 obj,u64 ancestor){(void)m;for(int i=0;obj&&obj<0x80000&&i<64;i++,obj=parents[obj/0x1000])if(obj==ancestor)return 1;return 0;}
static int ui_tab_state(u64 m,UiTabState* s){(void)m;s->current=page_current;s->page=0x5000;return page_ok;}
static int g_hotkey_tab=-1,g_hotkey_frames,g_char_page,g_char_tab=-1;
static int ui_tab_select_slot(const CPU* c,u64 m,const UiTabState* s,int t){(void)c;(void)m;(void)s;(void)t;return 0;}
static int ui_code(u64 pc){return pc>=0x8005000&&pc<0x8c78000&&!(pc&3);}
static int ui_inside(UiPick* p,u64 obj){float r[4];memcpy(r,GP(obj+0x88),sizeof r);return clip_ok&&p->point[0]>=r[0]&&p->point[0]<r[2]&&p->point[1]>=r[1]&&p->point[1]<r[3];}
static int pointer_pixel(const CPU* c,const PointerPress* p,int out[2]){(void)c;if(!pixel_ok)return 0;out[0]=(int)(p->x*p->width);out[1]=(int)(p->y*p->height);return 1;}
static int guest_call(const CPU* c,u64 pc,const u64* a,unsigned n,const float* f,unsigned nf,GuestResult* r){
 if(pc==0x83AD9D0){u64 pointer;u32 capacity;if(!read64(a[0]+0x398,&pointer)||!read32(a[0]+0x3a0,&capacity)||strlen((char*)GP(a[1]))+1>capacity)return 0;memcpy(GP(pointer),GP(a[1]),strlen((char*)GP(a[1]))+1);return 1;}
 (void)c;(void)n;(void)f;(void)nf;
 if(pc==0x832D180){w64(0x73000,focus_key);r->x0=0x73000;return focus_ok;}
 if(pc==0x8350BF0){float point[2]={(float)*(int*)GP(a[0]),(float)*(int*)GP(a[0]+4)};memcpy(GP(a[1]),point,8);return 1;}
 if(pc==0x8419000||pc==0x8427580||pc==0x81DF930||pc==0x81A5E90){action_calls++;action_id=(u32)a[2];return 1;}
 if(pc==0x838F650){u64 key,data,count;read64(a[1],&key);read64(a[0],&data);read64(a[0]+8,&count);if(count>32)return 0;for(u32 j=0;j<count;j++){u64 k;read64(data+j*16+8,&k);if(k==key){if(a[2]!=(a[0]==0x2e168?0x83848A0:0x81FC6C0)){unexpected_calls++;return 0;}highlight_calls++;selected_calls++;if(a[0]!=0x2e168)w32(a[0]-0xd0+0x150,categories[key-100]);w32(a[0]+0x28,j);return 1;}}return 0;}
 unexpected_calls++;return 0;
}
static void ui_click(const CPU* cpu,const PointerPress* p){(void)cpu;(void)p;click_calls++;page_current=1;}
static int primary_event(CPU* cpu,u64* e){(void)cpu;*e=1;return 1;}
static void original_ui(CPU* c,u64 entry){(void)entry;c->pc=c->x[30];c->x[0]=fake_blocked;}
static void (*g_ui_original)(CPU*,u64)=original_ui;
'''

CASES = r'''
static void rect(u64 obj,float x,float y){wf(obj+0x88,x);wf(obj+0x8c,y);wf(obj+0x90,x+20);wf(obj+0x94,y+20);}
static void reset(int skill){
 memset(memory,0,sizeof memory);memset(keys,0,sizeof keys);memset(parents,0,sizeof parents);
 g_have_pointer=g_have_hover=g_cancel=g_busy=0;g_enabled=g_ui_blocked=1;g_frames=100;
 g_ui_read=g_ui_count=g_item_drag_active=0;
 g_skill_read=g_skill_count=0;
 page_current=skill;page_ok=clip_ok=pixel_ok=focus_ok=fake_blocked=1;
 selected_calls=unexpected_calls=click_calls=log_calls=highlight_calls=action_calls=native_actions=0;action_id=0xffffffff;focus_key=UINT64_MAX;
 slot_count=14;for(u32 i=0;i<32;i++)categories[i]=i;
 keys[1]=1;keys[2]=3;w32(0x1018,4);w32(0x2018,4);parents[5]=0x1000;parents[6]=0x5000;parents[7]=0x6000;
 for(unsigned i=5;i<40;i++)w32(i*0x1000+0x18,4);
 keys[6]=ui_path_key(skill?"root.normallayer.consoleskillselection_main.layoutroot":"root.normallayer.consoleinventoryring_main.layoutroot");
 keys[7]=ui_path_key(skill?"root.normallayer.consoleskillselection_main.layoutroot.skillloadout":"root.normallayer.consoleinventoryring_main.layoutroot.inventoryring");
 w64(0x7000,0x90AF208);w64(0x7030,77);w64(0x7048,0x2f000);w64(0x7060,0x31000);w32(0x7068,skill?14:15);
 w64(0x9157F58,0x30000);w64(0x30000,0x2f000);w64(0x2f000,0x90AAEE0);w32(0x2f018,1);w32(0x2f150,13);
 w64(0x2f0d0,0x3e000);w64(0x2f0d8,14);w64(0x2f0e8,77);w64(0x2f0f0,ui_path_key("root.normallayer.consoleinventoryring_main.layoutroot.inventoryring.ringglow.cursor"));w32(0x2f0f8,0);w32(0x2f0fc,1);w32(0x2f100,1);
 w64(0x9158040,0x30010);w64(0x30010,0x2e000);w64(0x2e168,0x32000);w64(0x2e170,11);w32(0x2e190,10);
 w64(0x9158068,0x83848A0);
 w64(0x914F840,0x34000);w64(0x34010,0x35000);w64(0x35b80,0x36000);w64(0x36000,1);
 w64(0x36010,0x37000);w64(0x37000,0x38000);w32(0x37008,1);w64(0x38000,0x6000);
 w64(0x6000,0x33000);w64(0x330b0,0x83B81F0);w64(0x6118,0x33100);w64(0x33120,skill?0x8387180:0x81FB910);
 static const char* names[]={"button_armleft","button_armright","button_fingerright","button_neck","button_fingerleft","button_hands","button_shoulder","button_torso","button_head","button_waist","button_legs","button_feet","button_bracers","button_bag"};
 for(unsigned i=0;i<(skill?11u:14u);i++){
  u64 obj=(8+i)*0x1000;parents[8+i]=0x7000;w64(obj,skill?0x90ABB48:0x90AF208);w64(obj+0x38,77);w64(obj+0x30,100+i);rect(obj,30.0f*i,100);
  if(skill){w64(0x31000+(i+3)*24+8,obj);w64(0x32000+i*16+8,100+i);}
  else{char path[200];snprintf(path,sizeof path,"root.normallayer.consoleinventoryring_main.layoutroot.inventoryring.%s",names[i]);keys[8+i]=ui_path_key(path);w64(0x3e000+(13-i)*16+8,100+i);}
 }
}
static void reset_kadala(void){
 reset(0);page_ok=0;focus_key=UINT64_MAX;
 w64(0x9152080,0x4f000);w64(0x4f000,0x4f010);w64(0x4f028,0x53000);w64(0x4f118,0x53000);
 w64(0x53000,0x53100);w64(0x53008,1);w32(0x53018,0);w32(0x5301c,0);
 w64(0x53100,0);w64(0x53108,0);w32(0x53110,1);
 w64(0x9153278,0x4f200);w64(0x4f200,0x4f210);w64(0x4f210,0x90A29E8);w64(0x90A29E8+0x48,0x81A3490);
 w32(0x4f210+0xc,0);w32(0x4f210+0x18,1);w32(0x4f210+0x200,0);
 keys[60]=ui_path_key("root.normallayer.consoleinventoryring_main");keys[61]=ui_path_key("root.normallayer.consolebuttonlegend_main.layoutroot.buttonlegend");
 parents[80]=0x1000;parents[81]=0x1000;w32(0x50018,4);w32(0x51018,4);
 w64(0x51088,0);wf(0x5108c,608.0f);wf(0x51090,960.0f);wf(0x51094,688.0f);
 w64(0x51398,0x52000);w32(0x513a0,100);strcpy((char*)GP(0x52000),"{icon:button1,2.0}\xE8\xB4\xAD\xE4\xB9\xB0      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");
}
static CPU cpu;
static void reset_service(u32 group,u32 index){
 reset(0);page_ok=0;keys[5]=ui_path_key("root.normallayer.consoleinventoryring_main");
 w32(0x2f018,0);w32(0x2f150,12);
 const u64 holder[]={0x9158028,0x91598B0,0x9159948,0x9153E68};
 const u64 vt[]={0x90AB418,0x90AFC60,0x90AFE78,0x90A3750};
 const u64 open[4][5]={{0x837DF30,0x837DF60,0x837DF90,0x837DFC0},
  {0x8419140,0x8419170,0x84191A0,0x84191D0,0x8419200},
  {0x84276A0,0x84276D0,0x8427720,0x8427780},
  {0x81DFB00,0x81DFB30,0x81DFB60,0x81DFB90}};
 const u64 close[4][5]={{0},{0},{0,0x8427700,0x8427750,0},{0}};
 unsigned service=group==2?0:group-4,count=group==5?5:4;
 u32 mode=service==0?(index==0?1:index==1?0:index):index;
 w64(0x9152080,0x39000);w64(0x39000,0x3a000);w64(0x3a000+group*8,0x3b000);w64(0x3a108,0x3b000);
 w64(0x3b000,0x3c000);w64(0x3b008,count);w32(0x3b018,index);w32(0x3b01c,0);
 for(unsigned i=0;i<count;i++){w64(0x3c000+i*0x18,open[service][i]);w64(0x3c008+i*0x18,close[service][i]);w32(0x3c010+i*0x18,1);}
 w64(holder[service],0x3d000);w64(0x3d000,0x41000);w64(0x41000,vt[service]);w32(0x41018,1);w32(0x41200,mode);w32(0x41150,13);
 memcpy(GP(0x410d0),GP(0x2f0d0),0x38);
 w64(0x7048,0x41000);
 keys[40]=ui_path_key("root.normallayer.consolebuttonlegend_main.layoutroot.buttonlegend");
 parents[40]=0x1000;w32(0x28018,4);w64(0x28000,0x90AE520); w64(0x28038,1); w64(0x28030,200);
 wf(0x28088,0);wf(0x2808c,630);wf(0x28090,960);wf(0x28094,710);
 w64(0x28398,0x61000);w32(0x283a0,100);strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE6\x89\x93\xE9\x80\xA0      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");
 w64(0x90AFC60+0x48,0x84154A0);w64(0x90AFE78+0x48,0x8425970);w64(0x90A3750+0x48,0x81DCA90);
 if(group==5&&index<2){
  static const char* weapon[]={"sword","crossbow","dagger","wand","mace","offhand","mighty","staff","axe","fist","bow","flail","scythe"};
  static const char* armor[]={"fingerleft","fingerright","neck","hands","shoulder","torso","head","waist","legs","feet","bracers","bag"};
  char prefix[160],path[200];snprintf(prefix,sizeof prefix,"root.normallayer.consoleinventoryring_main.layoutroot.artisan.%s",index?"blacksmitharmorring":"blacksmithweaponsring");
  slot_count=index?12:13;keys[7]=ui_path_key(prefix);w32(0x7068,slot_count+1);w64(0x410d8,slot_count);
  snprintf(path,sizeof path,"%s.ringglow.cursor",prefix);w64(0x410f0,ui_path_key(path));w32(0x41150,index?78:65);
  memset(GP(0x3e000),0,0x100);
  for(u32 i=0;i<slot_count;i++){snprintf(path,sizeof path,"%s.button_%s",prefix,index?armor[i]:weapon[i]);keys[8+i]=ui_path_key(path);categories[i]=(index?78:65)+i;w64(0x3e000+(slot_count-1-i)*16+8,100+i);}
 }
}
static void motion(unsigned slot){native_world_hover((30.0f*slot+10)/1000.0f,0.11f,1000,1000);}
static void tick(void){cpu.x[30]=123;world_ui(&cpu,UI_PC);}
static int failures,checks;
#define CHECK(name,condition) do{checks++;if(!(condition)){printf("FAIL %s\n",name);failures++;}}while(0)
int main(void){
 for(unsigned skill=0;skill<2;skill++)for(unsigned i=0;i<(skill?11u:14u);i++){
  reset(skill);w32(skill?0x2e190:0x2f150,(i+1)%(skill?11:14));motion(i);tick();u32 selected;read32(skill?0x2e190:0x2f150,&selected);
  CHECK("hover-selects-only-requested-category",selected_calls==1&&selected==i&&!click_calls&&!unexpected_calls);
  CHECK("hover-reuses-native-highlight",highlight_calls==1&&*(u32*)GP(skill?0x2e190:0x2f0f8)==(skill?i:13-i));
 }
 reset(1);motion(0);motion(2);tick();CHECK("coalesces-latest-motion",selected_calls==1&&*(u32*)GP(0x2e190)==2);
 reset(1);motion(10);tick();CHECK("same-category-is-quiet",selected_calls==0&&log_calls==0);
 reset(1);motion(2);g_frames+=5;tick();CHECK("stale-motion-dropped",selected_calls==0);
 reset(1);g_frames=UINT32_MAX-1;motion(2);g_frames=1;tick();CHECK("frame-wrap-young-motion",selected_calls==1);
 reset(1);motion(2);g_world_command=3;native_world_cancel();tick();CHECK("cancel-clears-hover-and-world-command",selected_calls==0&&g_world_command==0);
 reset(1);PointerPress event;
 native_world_click(.1f,.1f,1000,1000,NATIVE_POINTER_UI_DOWN);
 native_world_click(.2f,.2f,1000,1000,NATIVE_POINTER_UI_UP);
 CHECK("ui-pair-down-first",take_pointer(&event)&&event.fallback==NATIVE_POINTER_UI_DOWN&&event.x==.1f);
 CHECK("ui-pair-up-second",take_pointer(&event)&&event.fallback==NATIVE_POINTER_UI_UP&&event.x==.2f);
 CHECK("ui-pair-drained",!take_pointer(&event));
 g_item_drag_active=1;native_world_click(.1f,.1f,1000,1000,NATIVE_POINTER_UI_DOWN);native_world_cancel();
 CHECK("cancel-discards-ui-pair-and-drag",!take_pointer(&event)&&!g_item_drag_active);
 reset(1);for(int n=0;n<16;n++)CHECK("ui-queue-bounded-accept",native_world_click(.1f,.1f,1000,1000,NATIVE_POINTER_UI_DOWN));
 g_item_drag_active=1;CHECK("ui-queue-overflow-cancels",!native_world_click(.1f,.1f,1000,1000,NATIVE_POINTER_UI_UP)&&!g_ui_count&&!g_item_drag_active);
 reset(1);motion(2);native_world_click(.1f,.1f,1000,1000,0);tick();CHECK("click-discards-old-motion",click_calls==1&&selected_calls==0);
 reset(1);native_world_click(.1f,.1f,1000,1000,0);motion(2);tick();CHECK("click-wins-same-tick",click_calls==1&&selected_calls==0&&!g_have_hover);
 reset(1);motion(2);fake_blocked=0;tick();fake_blocked=1;tick();CHECK("world-return-discards-motion",selected_calls==0&&!g_have_hover);
 reset(1);g_ui_blocked=0;motion(2);CHECK("no-world-motion-queued",!g_have_hover);
 reset(1);native_world_hover(NAN,.1f,1000,1000);CHECK("nan-rejected",!g_have_hover);
 reset(1);native_world_hover(1,.1f,1000,1000);CHECK("outside-rejected",!g_have_hover);
 reset(1);motion(2);native_world_hover(1,.1f,1000,1000);tick();CHECK("outside-clears-older-motion",selected_calls==0);
 reset(1);native_world_hover(.1f,.1f,0,1000);CHECK("empty-viewport-rejected",!g_have_hover);
 reset(1);page_ok=0;motion(2);tick();CHECK("other-player-or-group-rejected",selected_calls==0);
 reset(1);page_current=2;motion(2);tick();CHECK("nonwheel-page-rejected",selected_calls==0);
 reset(1);w32(0x37008,0);motion(2);tick();CHECK("unsubscribed-rejected",selected_calls==0);
 reset(1);w64(0x33120,0x81FB910);motion(2);tick();CHECK("wrong-owner-callback-rejected",selected_calls==0);
 reset(1);w32(0x37008,1025);motion(2);tick();CHECK("subscriber-bound",selected_calls==0);
 reset(1);w32(0x37008,2);w64(0x38008,0x22000);parents[34]=0x2000;w32(0x22018,4);motion(2);tick();CHECK("toplayer-blocks-hover",selected_calls==0);
 reset(1);w32(0x37008,2);w64(0x38008,0x22000);parents[34]=0x2000;w32(0x22018,0);motion(2);tick();CHECK("hidden-modal-does-not-block",selected_calls==1);
 reset(1);w32(0x37008,2);w64(0x38008,0x22000);parents[34]=0x1000;w32(0x22018,4);w64(0x22000,0x33000);w64(0x22118,0x33100);motion(2);tick();CHECK("other-normal-callback-owner-blocks",selected_calls==0);
 reset(1);focus_key=999;motion(2);tick();CHECK("unknown-focus-blocks",selected_calls==0);
 reset(1);keys[34]=999;parents[34]=0x1000;focus_key=999;motion(2);tick();CHECK("focus-outside-page-blocks",selected_calls==0);
 reset(1);clip_ok=0;motion(2);tick();CHECK("clipped-icon-blocks",selected_calls==0);
 reset(1);pixel_ok=0;motion(2);tick();CHECK("letterbox-rejected",selected_calls==0);
 reset(1);native_world_hover(.7f,.5f,1000,1000);tick();CHECK("outside-wheel-no-actions",selected_calls==0&&!unexpected_calls&&!click_calls);
 reset(0);w32(0x2f018,0);motion(2);tick();CHECK("inactive-equipment-controller",selected_calls==0);
 const u32 groups[]={2,5,6,7};
 for(unsigned g=0;g<4;g++)for(u32 mode=0;mode<(groups[g]==5?5u:4u);mode++)for(u32 slot=0;slot<(groups[g]==5&&mode<2?(mode?12u:13u):14u);slot++){
  reset_service(groups[g],mode);w32(0x41150,categories[(slot+1)%slot_count]);motion(slot);tick();
  CHECK("service-hover-uses-own-controller",selected_calls==1&&*(u32*)GP(0x41150)==categories[slot]&&*(u32*)GP(0x2f150)==12&&!unexpected_calls&&!click_calls);
  CHECK("service-hover-reuses-native-highlight",highlight_calls==1&&*(u32*)GP(0x410f8)==slot_count-1-slot&&*(u32*)GP(0x2f0f8)==0);
 }
 reset_service(7,0);UiPick click={&cpu,1,{70,110},0};
 CHECK("service-click-uses-own-controller",ui_equipment_icon(&click,8)==1&&selected_calls==1&&*(u32*)GP(0x41150)==2&&*(u32*)GP(0x2f150)==12);
 reset_service(7,0);w32(0x4100c,1);motion(2);tick();CHECK("service-controller-other-player",selected_calls==0);
 reset_service(7,0);w32(0x3b01c,1);motion(2);tick();CHECK("service-group-other-player",selected_calls==0);
 reset_service(7,0);w32(0x41200,1);motion(2);tick();CHECK("service-mode-mismatch",selected_calls==0);
 reset_service(7,0);w64(0x41000,0x90AFE78);motion(2);tick();CHECK("service-vtable-mismatch",selected_calls==0);
 reset_service(7,0);w32(0x41018,0);motion(2);tick();CHECK("service-inactive",selected_calls==0);
 reset_service(7,0);w32(0x41150,14);motion(2);tick();CHECK("service-invalid-current-category",selected_calls==0);
 reset_service(7,0);w64(0x3a030,0x3b000);motion(2);tick();CHECK("service-ambiguous-group",selected_calls==0);
 reset_service(6,1);w64(0x3c020,0);motion(2);tick();CHECK("service-missing-mixed-close",selected_calls==0);
 reset_service(7,0);w32(0x7018,0);motion(2);tick();CHECK("service-hidden-ring",selected_calls==0);
 reset_service(7,0);w32(0x37008,2);w64(0x38008,0x22000);parents[34]=0x2000;w32(0x22018,4);motion(2);tick();CHECK("service-toplayer-isolation",selected_calls==0);
 reset_service(7,0);w64(0x38000,0);motion(2);tick();CHECK("service-unsubscribed-owner",selected_calls==0);
 reset_service(7,0);keys[34]=999;parents[34]=0x1000;focus_key=999;motion(2);tick();CHECK("service-focus-outside-page",selected_calls==0);
 reset(0);w32(0x2f150,2);motion(2);tick();CHECK("repairs-stale-native-highlight",highlight_calls==1&&*(u32*)GP(0x2f0f8)==11);
 reset(0);w32(0x2f150,2);w32(0x2f0f8,11);motion(2);tick();CHECK("same-category-and-highlight-quiet",!highlight_calls&&!selected_calls);
 reset(0);w64(0x2f0f0,123);motion(2);tick();CHECK("wrong-highlight-owner-blocked",!highlight_calls&&!selected_calls);
 reset(0);w32(0x2f0fc,0);motion(2);tick();CHECK("disabled-native-selector-blocked",!highlight_calls&&!selected_calls);
 reset(0);w64(0x3e000+10*16+8,102);motion(2);tick();CHECK("duplicate-native-slot-blocked",!highlight_calls&&!selected_calls);
 reset(0);w64(0x7048,0x41000);motion(2);tick();CHECK("wrong-native-controller-binding-blocked",!highlight_calls&&!selected_calls);
 reset(1);w64(0x9158068,0x81FC6C0);motion(2);tick();CHECK("wrong-skill-native-highlight-callback-blocked",!highlight_calls&&!selected_calls);
 reset_service(5,0);w32(0x7068,15);motion(2);tick();CHECK("weapon-wrong-child-count",!selected_calls);
 reset_service(5,1);w64(0x410d8,13);motion(2);tick();CHECK("armor-wrong-selector-count",!selected_calls);
 reset_service(5,0);w32(0x41150,64);motion(2);tick();CHECK("weapon-invalid-current-category",!selected_calls);
 reset_service(5,1);w32(0x41150,77);motion(2);tick();CHECK("armor-invalid-current-category",!selected_calls);
 reset_service(5,0);w32(0x410fc,0);motion(2);tick();CHECK("weapon-disabled-selector",!selected_calls);
 reset_service(5,0);w32(0x37008,2);w64(0x38008,0x22000);parents[34]=0x2000;w32(0x22018,4);motion(2);tick();CHECK("weapon-modal-isolation",!selected_calls);
 reset_service(5,1);UiPick armor_click={&cpu,1,{70,110},0};CHECK("armor-click-native-category",ui_equipment_icon(&armor_click,8)==1&&*(u32*)GP(0x41150)==80&&highlight_calls==1);
 reset_service(5,0);action_calls=0;UiPick craft_click={&cpu,1,{120,650},0};
 CHECK("blacksmith-footer-craft-click",ui_service_action_click(&craft_click,42)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(5,2);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE5\x88\x86\xE8\xA7\xA3      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick salvage_click={&cpu,1,{120,650},0};CHECK("blacksmith-salvage-footer-click",ui_service_action_click(&salvage_click,49)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(5,3);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE4\xBF\xAE\xE5\xA4\x8D      {icon:button3,2.0}\xE4\xBF\xAE\xE5\xA4\x8D\xE8\xA3\x85\xE5\xA4\x87\xE7\x89\xA9\xE5\x93\x81");UiPick repair_click={&cpu,1,{120,650},0};CHECK("blacksmith-repair-footer-click",ui_service_action_click(&repair_click,50)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(5,4);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE8\xAE\xAD\xE7\xBB\x83      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick train_click={&cpu,1,{120,650},0};CHECK("blacksmith-training-footer-click",ui_service_action_click(&train_click,51)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(5,2);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0} 打造");UiPick salvage_wrong={&cpu,1,{120,650},0};CHECK("blacksmith-salvage-wrong-label",ui_service_action_click(&salvage_wrong,52)==0&&!action_calls);
 
 reset_service(6,3);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE8\xAE\xAD\xE7\xBB\x83      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick jewelry_train={&cpu,1,{120,650},0};CHECK("jeweler-training-footer-click",ui_service_action_click(&jewelry_train,53)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(7,3);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE8\xAE\xAD\xE7\xBB\x83      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick mystic_train={&cpu,1,{120,650},0};CHECK("mystic-training-footer-click",ui_service_action_click(&mystic_train,54)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(6,0);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9      {icon:button2,2.0}\xE5\x85\xB3\xE9\x97\xAD");UiPick jew_sel={&cpu,1,{120,650},0};CHECK("jeweler-combine-select-footer",ui_service_action_click(&jew_sel,70)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(6,0);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE5\x90\x88\xE6\x88\x90      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick jew_craft={&cpu,1,{120,650},0};CHECK("jeweler-combine-craft-footer",ui_service_action_click(&jew_craft,71)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(6,0);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE7\xBB\xA7\xE7\xBB\xAD      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick jew_cont={&cpu,1,{120,650},0};CHECK("jeweler-combine-continue-footer",ui_service_action_click(&jew_cont,72)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(6,1);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x95\xB6\xE5\xAD\x94      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick jew_socket={&cpu,1,{120,650},0};CHECK("jeweler-socket-footer",ui_service_action_click(&jew_socket,73)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(6,2);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE7\xA7\xBB\xE9\x99\xA4      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick jew_remove={&cpu,1,{120,650},0};CHECK("jeweler-remove-footer",ui_service_action_click(&jew_remove,74)==1&&action_calls==1&&action_id==0&&!selected_calls);
 reset_service(6,1);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE5\x90\x88\xE6\x88\x90      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick jew_wrong={&cpu,1,{120,650},0};CHECK("jeweler-socket-wrong-label",ui_service_action_click(&jew_wrong,75)==0&&!action_calls);
 reset_service(6,3);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9      {icon:button2,2.0}\xE5\x85\xB3\xE9\x97\xAD");UiPick jew_train_wrong={&cpu,1,{120,650},0};CHECK("jeweler-training-select-rejected",ui_service_action_click(&jew_train_wrong,76)==0&&!action_calls);
 reset_service(6,0);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9");UiPick jew_right={&cpu,1,{500,650},0};CHECK("jeweler-combine-right-rejected",ui_service_action_click(&jew_right,77)==0&&!action_calls);
 reset_service(7,0);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9      {icon:button2,2.0}\xE5\x85\xB3\xE9\x97\xAD");UiPick mys_sel={&cpu,1,{120,650},0};CHECK("mystic-enchant-select-thunk",ui_service_action_click(&mys_sel,80)==1&&action_calls==1&&action_id==0&&!native_actions&&!selected_calls);
 reset_service(7,0);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9      {icon:button3,2.0}\xE6\x9F\xA5\xE7\x9C\x8B\xE5\x8F\xAF\xE6\x9B\xBF\xE6\x8D\xA2\xE7\x9A\x84\xE5\xB1\x9E\xE6\x80\xA7      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick mys_affix={&cpu,1,{120,650},0};CHECK("mystic-enchant-affix-native-a",ui_service_action_click(&mys_affix,81)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,0);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x99\x84\xE9\xAD\x94      {icon:button2,2.0}\xE5\x8F\x96\xE6\xB6\x88");UiPick mys_apply={&cpu,1,{120,650},0};CHECK("mystic-enchant-apply-native-a",ui_service_action_click(&mys_apply,82)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,0);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE6\x8E\xA5\xE5\x8F\x97");UiPick mys_accept={&cpu,1,{120,650},0};CHECK("mystic-enchant-accept-native-a",ui_service_action_click(&mys_accept,83)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,0);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button2,2.0}\xE5\x8F\x96\xE6\xB6\x88");UiPick mys_cancel={&cpu,1,{120,650},0};CHECK("mystic-enchant-cancel-confirm-native-a",ui_service_action_click(&mys_cancel,85)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,1);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9      {icon:button2,2.0}\xE5\x85\xB3\xE9\x97\xAD");UiPick tr_sel={&cpu,1,{120,650},0};CHECK("mystic-transmog-select-native-a",ui_service_action_click(&tr_sel,90)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,1);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9      {icon:button3,2.0}\xE5\xAF\xB9\xE6\xAF\x94      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick tr_list={&cpu,1,{120,650},0};CHECK("mystic-transmog-appearance-native-a",ui_service_action_click(&tr_list,91)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,1);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE5\xB9\xBB\xE5\x8C\x96      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick tr_apply={&cpu,1,{120,650},0};CHECK("mystic-transmog-apply-native-a",ui_service_action_click(&tr_apply,92)==1&&native_actions==1&&!action_calls&&!selected_calls);
 reset_service(7,1);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE8\xAE\xAD\xE7\xBB\x83      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick tr_wrong={&cpu,1,{120,650},0};CHECK("mystic-transmog-wrong-label",ui_service_action_click(&tr_wrong,93)==0&&!action_calls&&!native_actions);
 reset_service(7,0);action_calls=0;native_actions=0;strcpy((char*)GP(0x61000),"{icon:button1,2.0}\xE8\xAE\xAD\xE7\xBB\x83      {icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick mys_wrong={&cpu,1,{120,650},0};CHECK("mystic-enchant-wrong-label",ui_service_action_click(&mys_wrong,84)==0&&!action_calls&&!native_actions);
 reset_service(7,3);action_calls=0;w64(0x90A3750+0x48,0x81DCA94);UiPick mystic_wrong={&cpu,1,{120,650},0};CHECK("mystic-training-method-rejected",ui_service_action_click(&mystic_wrong,55)==0&&!action_calls);
 reset_service(5,0);action_calls=0;UiPick craft_right={&cpu,1,{500,650},0};CHECK("blacksmith-footer-right-rejected",ui_service_action_click(&craft_right,43)==0&&!action_calls);
 reset_service(5,0);action_calls=0;strcpy((char*)GP(0x61000),"{icon:button2,2.0}\xE8\xBF\x94\xE5\x9B\x9E");UiPick craft_text={&cpu,1,{120,650},0};CHECK("blacksmith-footer-label-rejected",ui_service_action_click(&craft_text,44)==0&&!action_calls);
 reset_service(5,1);action_calls=0;UiPick craft_page={&cpu,1,{120,650},0};CHECK("blacksmith-footer-wrong-page",ui_service_action_click(&craft_page,45)==0&&!action_calls);
 reset_service(7,0);action_calls=0;UiPick craft_group={&cpu,1,{120,650},0};CHECK("blacksmith-footer-wrong-group",ui_service_action_click(&craft_group,46)==0&&!action_calls);
 reset_service(5,0);action_calls=0;w64(0x90AFC60+0x48,0x84154A4);UiPick craft_method={&cpu,1,{120,650},0};CHECK("blacksmith-footer-method-rejected",ui_service_action_click(&craft_method,47)==0&&!action_calls);
 reset_service(5,0);action_calls=0;w32(0x37008,2);w64(0x38008,0x22000);parents[34]=0x2000;w32(0x22018,4);UiPick craft_modal={&cpu,1,{120,650},0};CHECK("blacksmith-footer-modal-rejected",ui_service_action_click(&craft_modal,48)==0&&!action_calls);
 reset_kadala();action_calls=0;w32(0x4f210+0x200,2);UiPick kadala_mode={&cpu,1,{90,650},0};CHECK("kadala-mode-rejected",ui_kadala_action_click(&kadala_mode,61)==0&&!action_calls);
 reset_kadala();action_calls=0;w64(0x90A29E8+0x48,0x81A3494);UiPick kadala_method={&cpu,1,{90,650},0};CHECK("kadala-method-rejected",ui_kadala_action_click(&kadala_method,62)==0&&!action_calls);
 reset_kadala();action_calls=0;strcpy((char*)GP(0x52000),"{icon:button1,2.0}\xE9\x80\x89\xE6\x8B\xA9");UiPick kadala_text={&cpu,1,{90,650},0};CHECK("kadala-label-rejected",ui_kadala_action_click(&kadala_text,63)==0&&!action_calls);
 reset_kadala();action_calls=0;UiPick kadala_right={&cpu,1,{700,650},0};CHECK("kadala-right-rejected",ui_kadala_action_click(&kadala_right,64)==0&&!action_calls);
 reset(0);g_ui_blocked=0;PointerPress skill_press;
 native_world_click(.1f,.2f,1000,1000,NATIVE_POINTER_SKILL|NATIVE_POINTER_SLOT(2));
 native_world_click(.3f,.4f,1000,1000,NATIVE_POINTER_SKILL|NATIVE_POINTER_SLOT(3));
 native_world_click(.5f,.6f,1000,1000,0);
 CHECK("skill-queue-preserves-first-digit",take_pointer(&skill_press)&&((skill_press.fallback>>8)&255)==2&&skill_press.x==.1f);
 CHECK("skill-queue-preserves-second-digit",take_pointer(&skill_press)&&((skill_press.fallback>>8)&255)==3&&skill_press.x==.3f);
 CHECK("movement-does-not-overwrite-skill",take_pointer(&skill_press)&&!skill_press.fallback&&skill_press.x==.5f);
 CHECK("skill-queue-drained",!take_pointer(&skill_press));
 reset(0);for(unsigned index=0;index<8;index++)native_world_click(.1f,.2f,1000,1000,NATIVE_POINTER_SKILL|NATIVE_POINTER_SLOT(2));
 CHECK("skill-queue-overflow-rejects-new-only",!native_world_click(.1f,.2f,1000,1000,NATIVE_POINTER_SKILL|NATIVE_POINTER_SLOT(3))&&g_skill_count==8);
 native_world_cancel();CHECK("cancel-clears-pending-skills",!take_pointer(&skill_press));
 reset(0);native_world_click(.1f,.2f,1000,1000,NATIVE_POINTER_SKILL|NATIVE_POINTER_SLOT(2));tick();
 CHECK("pending-world-skill-cannot-click-ui",!g_skill_count&&!click_calls);
 printf("%d checks; %d failures\n",checks,failures);return failures?1:0;
}
'''


def function(source: str, name: str) -> str:
    import re
    start = re.search(r"^(?:static )?(?:int|void|u64) " + name + r"\([^;{}]*\)\s*\{", source, re.M).start()
    body = source.index("{", start)
    depth = 0
    tokens = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    for token in tokens.finditer(source, body):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return source[start:token.end()] + "\n"
    raise ValueError("unterminated function: " + name)


def close_slice(source: str) -> str:
    """0076 publishes a Space close snapshot; 0075 has no close path at all."""
    if "UiCloseTarget" not in source:
        return ""
    declarations = source[source.index("typedef struct {\n    u64 owner, context, model;"):
                          source.index("/* Last click's goal kind")]
    # This suite never requests a close, so the game-thread tick is a no-op that
    # only keeps the production snapshot globals read (the build is -Werror).
    stub = ("static int ui_close_tick(const CPU* cpu,u64 map,u64 manager){(void)cpu;(void)map;(void)manager;\n"
            " return (int)(g_close_scope|g_close_target.kind|g_close_pending.kind)&0;}\n")
    return declarations + stub


def compare_slice(source: str, close_text: str) -> str:
    """0077 adds item hover and Alt compare; this suite keeps them out of scope."""
    if "ui_item_hover" not in source or "ui_compare_tick" not in source:
        return ""
    parts = []
    if "g_compare_owner" not in close_text:
        parts.append("static u64 g_compare_owner;\n")
    parts.append("static int ui_item_hover(UiPick* p) { (void)p; return 0; }\n")
    parts.append("static void ui_compare_tick(const CPU* cpu, u64 map) { (void)cpu; (void)map; "
                 "if (g_compare_owner) return; }\n")
    return "".join(parts)


def main() -> int:
    source = SOURCE.read_text("utf-8")
    names = ["take_pointer", "native_world_click", "native_world_hover", "take_hover",
             "native_world_cancel", "ui_path_key", "ui_service_state", "ui_wheel_allowed", "ui_text_contains",
             "ui_service_action_click", "ui_kadala_action_click", "ui_equipment_icon", "ui_skill_icon", "ui_hover", "ui_footer_relabel", "world_ui"]
    declarations = source[source.index("/* Service ABI whitelist"):source.index("static int ui_service_state(")]
    close = close_slice(source)
    code = PRELUDE + close + compare_slice(source, close) + declarations + "\n".join(function(source, n) for n in names) + CASES
    OUT.mkdir(parents=True, exist_ok=True)
    c, exe = OUT / "hover.c", OUT / "hover.exe"
    c.write_text(code, "utf-8")
    cc = "D:/workspace/msys2/msys64/clang64/bin/clang.exe"
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout, end="")
    (OUT / "result.json").write_text(json.dumps({
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "scope": __doc__, "returncode": result.returncode, "stdout": result.stdout,
    }, indent=2), "utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

