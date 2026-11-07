"""Verify native text re-layout and action routing after keyboard/mouse relabeling."""
from pathlib import Path
import subprocess

from test_hover_wheel import function

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "reference/ScarletNX-src/src/nx/runtime/native_world.c"
OUTPUT = ROOT / "out/windows/kbm/session/footer-label-tests"

PRELUDE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { int unused; } CPU;
typedef struct { const CPU* cpu; u64 map; float point[2]; } UiPick;
static unsigned char memory[0x40000];
static u64 g_stack_top=0x30000,g_footer_object,pressed;
static char g_footer_original[512],g_footer_display[512],layout[512];
static int setters,visible=1,fail_setter;
static u64 footer_key;
#define GP(address) (memory+(address))
#define LOG(...) do{if(0)printf(__VA_ARGS__);}while(0)
static int readable(u64 address,size_t size){return address&&address<sizeof memory&&size<=sizeof memory-address;}
static int read32(u64 address,u32* value){if(!readable(address,4))return 0;memcpy(value,GP(address),4);return 1;}
static int read64(u64 address,u64* value){if(!readable(address,8))return 0;memcpy(value,GP(address),8);return 1;}
static void write32(u64 address,u32 value){memcpy(GP(address),&value,4);}
static void write64(u64 address,u64 value){memcpy(GP(address),&value,8);}
static u64 ui_object(u64 map,u64 key){(void)map;return key==footer_key?0x1000:0;}
static int ui_visible(u64 map,u64 object){(void)map;return object==0x1000&&visible;}
static int ui_inside(UiPick* pick,u64 object){return object==0x1000&&pick->point[0]>=0&&pick->point[0]<960&&pick->point[1]>=600&&pick->point[1]<680;}
static int native_action_press(u64 pad){pressed=pad;return 1;}
static int guest_call(const CPU* cpu,u64 pc,const u64* args,unsigned count,const float* floats,unsigned float_count,void* result){
 (void)cpu;(void)floats;(void)float_count;(void)result;
 if(pc!=0x83AD9D0||count!=3||args[0]!=0x1000||args[2]!=1||fail_setter)return 0;
 if(!strcmp((char*)GP(0x2000),(char*)GP(args[1])))return 0;
 strcpy(layout,(char*)GP(args[1]));strcpy((char*)GP(0x2000),layout);setters++;return 1;
}
'''

CASES = r'''
static int failures,checks;
#define CHECK(name,condition) do{checks++;if(!(condition)){printf("FAIL %s\n",name);failures++;}}while(0)
static void reset(const char* text){
 memset(memory,0,sizeof memory);memset(g_footer_original,0,sizeof g_footer_original);memset(g_footer_display,0,sizeof g_footer_display);
 g_footer_object=pressed=0;setters=fail_setter=0;visible=1;layout[0]=0;
 footer_key=ui_path_key("root.normallayer.consolebuttonlegend_main.layoutroot.buttonlegend");
 write64(0x1398,0x2000);write32(0x13a0,512);strcpy((char*)GP(0x2000),text);
 float rectangle[]={0,600,960,680};memcpy(GP(0x1088),rectangle,sizeof rectangle);
}
int main(void){
 UiPick pick={NULL,1,{120,640}};
 const char* original="{icon:button1,2.0} Select      {icon:button3,2.0} Compare      {icon:button4,2.0} Clear      {icon:button2,2.0} Close";
 reset(original);ui_footer_relabel(NULL,1);
 CHECK("native-setter-rebuilds-layout",setters==1&&strstr(layout,"[Esc]")&&strstr(layout,"[Alt]"));
 CHECK("all-face-hints-replaced",!strstr(layout,"{icon:button"));
 CHECK("raw-original-preserved",!strcmp(g_footer_original,original));
 CHECK("displayed-string-matches-layout",!strcmp((char*)GP(0x2000),layout));
 ui_footer_relabel(NULL,1);CHECK("unchanged-layout-not-rebuilt",setters==1);
 CHECK("left-cell-original-action",ui_footer_legend_click(&pick,1)==1&&pressed==1);
 pick.point[0]=360;pressed=0;CHECK("compare-cell-original-action",ui_footer_legend_click(&pick,2)==1&&pressed==(1ull<<2));
 pick.point[0]=600;pressed=0;CHECK("clear-cell-original-action",ui_footer_legend_click(&pick,3)==1&&pressed==(1ull<<3));
 pick.point[0]=840;pressed=0;CHECK("close-cell-original-action",ui_footer_legend_click(&pick,4)==1&&pressed==(1ull<<1));
 reset("{icon:button1} Dye      {icon:l3} Remove      {icon:button2} Close");ui_footer_relabel(NULL,1);
 pick.point[0]=360;pressed=0;CHECK("click-label-preserves-l3",ui_footer_legend_click(&pick,5)==1&&pressed==(1ull<<4));
 reset("{icon:button1} Travel      {icon:button2} Close      {icon:l2} Bounties      {icon:r2} Bosses");ui_footer_relabel(NULL,1);
 CHECK("trigger-labels",strstr(layout,"[1]")&&strstr(layout,"[3]"));
 pick.point[0]=600;pressed=0;CHECK("left-trigger-action",ui_footer_legend_click(&pick,6)==1&&pressed==(1ull<<8));
 pick.point[0]=840;pressed=0;CHECK("right-trigger-action",ui_footer_legend_click(&pick,7)==1&&pressed==(1ull<<9));
 reset(original);fail_setter=1;ui_footer_relabel(NULL,1);CHECK("failed-setter-keeps-original",!setters&&!g_footer_object&&!strcmp((char*)GP(0x2000),original));
 reset(original);visible=0;ui_footer_relabel(NULL,1);CHECK("hidden-footer-untouched",!setters);
 reset("{icon:button1 Select");ui_footer_relabel(NULL,1);CHECK("unterminated-tag-untouched",!setters);
 reset(original);memset(GP(0x2000),'x',512);ui_footer_relabel(NULL,1);CHECK("unterminated-buffer-untouched",!setters);
 reset(original);ui_footer_relabel(NULL,1);strcpy((char*)GP(0x2000),"{icon:button2} Other");pick.point[0]=120;pressed=0;
 CHECK("new-legend-invalidates-cached-routing",ui_footer_legend_click(&pick,8)==1&&pressed==(1ull<<1));
 printf("%d footer label checks; %d failures\n",checks,failures);return failures?1:0;
}
'''


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    names = ("ui_path_key", "ui_footer_relabel", "ui_footer_legend_click")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    generated = OUTPUT / "footer.c"
    executable = OUTPUT / "footer.exe"
    generated.write_text(PRELUDE + "\n".join(function(source, name) for name in names) + CASES, encoding="utf-8")
    subprocess.run([
        "D:/workspace/msys2/msys64/clang64/bin/clang.exe", "-std=c11", "-Wall", "-Wextra", "-Werror",
        str(generated), "-o", str(executable),
    ], check=True)
    return subprocess.run([str(executable)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
