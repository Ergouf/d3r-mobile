# D3 原生键鼠改造 · 交接文档

交接时间：2026-11-01
方向复核及代码/实机评估：2026-11-01。先读 [KBM-METHOD-ASSESSMENT.md](KBM-METHOD-ASSESSMENT.md)；已纠正地址换算、探针 ABI 和扫描覆盖问题，后续按本版及 [KEYBOARD-MOUSE.md](KEYBOARD-MOUSE.md) 执行。
仓库：`D:\workspace\Diablo(fegnjl)`
分支：`feat/d3-native-kbm`（原交接基线 `2242387`；最新提交以 `git log -1` 为准，未配置远端）
范围：Windows / ScarletNX 运行时。目标是《暗黑破坏神 III：永恒合集》Switch 版的**原生 PC 键鼠**——鼠标指针命中 UI、点地板走位、点目标交互，而不是“键鼠当手柄”。

**执行约束：只做原生键鼠。停止 A/A+ 键鼠转手柄、鼠标转摇杆、虚拟手柄，以及“设焦点 + 合成 A”；不作为保底或交付退路。现有 A+ 代码只作历史记录，本轮增加 RE 评估与探针修复，未修改运行时或安装程序。**

每次开始任务先连接/启动 Serena 并激活正确项目，再优先使用符号概要、符号和引用查询，见根目录 AGENTS.md。所有电脑/浏览器界面操作、截图对照及视觉交互验收均委派给 GPT-6.1 Terra（gpt-6.1-terra）；不可用时说明，不改用其他模型执行。

续接链：`ses_e6ba759f7ffe9xA4khRsDT2sdK` ← `ses_e6d4415b7ffet3vd42jCf4hNuV` ← `ses_e6f21c51cffebi9w0DdqhO5prj`

> 接手先读本文第 1、5、6、7 节；设计背景见 [KEYBOARD-MOUSE.md](KEYBOARD-MOUSE.md)，逐轮证据见 [KBM-RE-EVIDENCE.md](KBM-RE-EVIDENCE.md)。
>
> 历史测试及工作区记录沿用原交接；其中“本轮”指 `ses_e6ba759f7ffe9xA4khRsDT2sdK`（2026-11-01）。标明“方向复核”“源码复核”的内容及执行约束属于本次文档修订。本次仅做报告所列的有限实机/内存对照，未复现历史 A+ 验收。第 5.3–5.4 节的 UI 对象注册表发现尚未合并进 `KBM-RE-EVIDENCE.md`（该文第 15 节截至原生调用桥）。

## 1. 一句话结论

**原生键鼠尚未实现；原生事件/动作层的调查值得继续，手柄映射路线停止。**

| 能力 | 状态 | 口径 |
| --- | --- | --- |
| 历史 A+ 从开始画面进入第一章 | 已记录，停止推进 | 鼠标位置驱动左摇杆，按键转 Npad；不计入原生进度 |
| 历史 A+ 移动、技能、暂停菜单 | 已记录，停止推进 | 同上，不能作为本任务交付 |
| 运行时内调用 guest 函数 | 最小探针曾返回 | 队列 + 独立栈；尚未确认 UI 主线程及真实业务上下文 |
| 枚举 UI 控件对象（名字/矩形/vtable） | ✅ 已打通 | 19k 对象的注册表，可按名字查 |
| 鼠标指针命中 UI 控件并点击 | ❌ 未完成 | 当前左键等于按 A，不是指针命中 |
| 鼠标点地板寻路、点目标交互 | ❌ 未完成 | 只有摇杆方向移动 |
| 原生鼠标/键盘分发、世界点击与上下文 | ❌ 未找到 | **当前主阻塞；菜单确认入口不能替代这些路径** |

最近一轮的净产出：触摸未表现为原生指针，控制台回调表未捕获普通确认事件，找到 **UI 对象注册表**。这张表适合定位特定对象和追踪原生事件入口；手写矩形命中、改焦点再发 A 不能替代原生鼠标分发。PC 字符串/资源仅是线索，不能保证 D3 保留了完整可执行的 PC 输入层。

## 2. 历史 A+ 记录（停止推进，不作为原生交付）

以下参数与结果仅解释已有实现，不安排重新验收或完善。原生调查必须关闭映射与鼠标触摸；后续命令见第 3.3、9 节。

历史启动参数：

```text
--fullscreen=0 --docked=0 --resolution=1 --mouse_steer=1 --touch=2
```

验收步骤（已多次复现）：

1. 片头结束，停在“按任意键”画面；左键一次 → 主菜单，`继续` 高亮。
2. 鼠标上移选中 `继续`，左键一次 → 读条 → 新崔斯特姆（第一章）。
3. 游戏内：鼠标相对窗口中心的方向/距离驱动 1P 左摇杆；左键 A、右键 B、中键 X、侧键 Y/L；WASD 仍可用。
4. `mouse_steer=1` 时触摸事件被门控，左键不会再被当成手指点开“英雄资料”。

证据（`out/` 已被 git 忽略，只在当前机器上）：

| 画面 | 文件 |
| --- | --- |
| 主菜单 / 点击后进入 | `out/windows/kbm/b2/70-click1.png`、`71-click2.png` |
| 新崔斯特姆可玩 | `out/windows/kbm/b2/102-playable.png`、`103-playable2.png`、`111-in-game.png` |
| 鼠标向东南移动 | `out/windows/kbm/b2/27-mouse-se.png` |

A+ 的已知限制（历史记录）：

- 菜单项不能“指哪点哪”，只能靠摇杆改变选中项再按 A；
- 摇杆是连续量，而主机菜单是 D-pad 边沿触发，暂停菜单里持续偏转只能移动一格；
- 暂停菜单焦点默认在右侧英雄头像，鼠标摇杆左移没有把焦点移到左侧列表（`110-pause-left.png`）。

## 3. 环境、构建与安装

### 3.1 路径

| 项 | 值 |
| --- | --- |
| 仓库 | `D:\workspace\Diablo(fegnjl)`（含括号，`settingsgen` 会截断 cmd 命令行） |
| 无括号构建路径 | `D:\workspace\Diablo-kbm`（junction → 仓库根） |
| 运行时源码 | `reference/ScarletNX-src`，基线 `dbf8915965367e8a9616b19e5a0c1eddafaf28f3` |
| 补丁 | `0001-fsr1-present-stats.patch`、`0002-mouse-steer.patch`、`0003-native-bridge.patch` |
| 工具链 | MSYS2 CLANG64，`D:\workspace\msys2\msys64`，clang 23.1.3 |
| 构建产物 | `out/windows/build-kbm/scarletnx.exe` |
| 安装目录 | `D:\Games\DiabloIII\01001B300B9BE000\` |
| 启动入口 | `D:\Games\DiabloIII\暗黑破坏神 III.lnk`（无控制台窗口） |

当前安装的运行时与 `out/windows/build-kbm/scarletnx.exe` **SHA-256 完全一致**：

```text
254FB541E06B3490EADDB41F49DA6BA4872B5E5604E0648A2E354F76784F3ABA
```

注意：`patches/windows/base.json` 里的 `runtime_release_sha256`（`194e5b59…`）是较早的 FSR 发行版，不是当前键鼠构建，不要拿它做本分支的验收。

### 3.2 构建

```powershell
cmd /c mklink /J D:\workspace\Diablo-kbm "D:\workspace\Diablo(fegnjl)"   # 已存在则跳过

cd D:\workspace\Diablo-kbm
.\patches\windows\Apply-Patches.ps1 -CheckOnly
.\tools\windows-dev\Build.ps1 -Configure `
  -SourcePath D:\workspace\Diablo-kbm\reference\ScarletNX-src `
  -BuildPath D:\workspace\Diablo-kbm\out\windows\build-kbm
.\tools\windows-dev\Build.ps1 `
  -SourcePath D:\workspace\Diablo-kbm\reference\ScarletNX-src `
  -BuildPath D:\workspace\Diablo-kbm\out\windows\build-kbm
```

已知坑：

- OpenSSL 外部工程在 `-j18` 下会因依赖文件竞争失败；进 `out/windows/build-kbm/openssl-build` 执行 `make -j1 build_libs`，再跑一次 `Build.ps1`。
- 换源码/改补丁后先跑 `Apply-Patches.ps1 -CheckOnly`；已完整应用会直接返回，不会重置工作树。
- 构建目录在 `out/`，`reference/ScarletNX-src` 也被 `.gitignore` 覆盖；两者都不要提交。

### 3.3 小窗口、后台、非置顶启动

tools/windows-dev/Launch-Background.ps1 默认窗口 1024×576、(40,40)、SWP_NOACTIVATE、非 topmost；但脚本的默认游戏参数仍是历史 A+（mouse_steer=1、touch=2）。原生探针显式覆盖，不能直接沿用默认启动：

```powershell
$nativeProbeArgs = @('--fullscreen=0', '--docked=0', '--resolution=1', '--mouse_steer=0', '--touch=0')
.\tools\windows-dev\Launch-Background.ps1 -GameArgs $nativeProbeArgs
.\tools\windows-dev\Launch-Background.ps1 -GameArgs $nativeProbeArgs -Width 1280 -Height 720 -X 60 -Y 60
```

以上只关鼠标映射/触摸，不会关闭现有键盘转 Npad；原生键盘验收还须隔离该旧路径。启动、发键鼠和截图等界面操作均由 Terra 子代理执行。

脚本只调用 SetWindowPos / ShowWindow(SW_SHOWNOACTIVATE)，不调用 SetForegroundWindow。截图可用 Capture-Screen.ps1 或 Capture-Window.ps1；后者的 PrintWindow 对 Vulkan 窗口可能返回旧帧。本轮未运行这些界面操作。

### 3.4 回退

安装目录保留了键鼠改造前的运行时：

```text
D:\Games\DiabloIII\backup-01001B300B9BE000-20261101-005555.exe
SHA-256 194E5B59CA8B8D155FAF0C242CE2C5BB3D6910A6E3A28A268924AED50E9878E5
```

它等于 `patches/windows/base.json` 的 `runtime_release_sha256`，不含 0002/0003。把它复制回 `01001B300B9BE000\01001B300B9BE000.exe` 即可回到纯 FSR 发行版行为（先备份当前文件，并重新核对 `SHA256SUMS.txt`）。

## 4. 运行时地址基线（只对当前构建有效）

### 4.1 符号偏移

`g_mem` / `g_disp` / `g_code_lo` 是 `scarletnx.exe` 里的全局符号；换构建必须重取：

```powershell
. .\tools\windows-dev\Activate.ps1
llvm-nm out\windows\build-kbm\scarletnx.exe | Select-String ' (g_mem|g_disp|g_code_lo)$'
```

`llvm-nm` 打印的是带 PE 首选基址 `0x140000000` 的地址，减去后才是 RVA。当前已验证：

| 符号 | RVA | 用途 |
| --- | --- | --- |
| `g_mem` | `0x17AEF20` | 指向 guest 地址 0 的宿主基址；`g_mem + guest 地址` 读模块内存 |
| `g_disp` | `0x12910D0` | host 函数分发表；`disp[(pc - g_code_lo) >> 2]` |
| `g_code_lo` | `0x17AF028` | 分发表的 guest 起点 |

guest 侧：`main` 模块基址 `0x8005000`，模块偏移 + `0x8005000` = 绝对 guest 地址。

### 4.2 代码基线：fixed ELF 与运行时已核验一致

2026-11-01 从 PID 13416 新 dump 并逐字节比较：当前 d3_main_fixed.elf 的 text（13,052,816 字节）、rodata（4,344,260 字节）与运行时及已有 b2 dump 都完全一致。旧“不一致”结论撤回。

错误出在地址换算：main 的真实基址是 0x8005000，而旧比较减了 0x8000000。guest 0x8366870 对应模块偏移 0x361870，不能读成 0x366870；两份正确位置都以 sub sp, sp, #0x160 开始。保持 guest 与模块偏移两列，不再混用。

新证据与 SHA-256 见 [方法评估](KBM-METHOD-ASSESSMENT.md) 和本机 out/windows/kbm/assessment-20261101/baseline-comparison.json。需要换构建时仍须重新核验指纹，不能把本次一致性扩展到其他版本。

本轮新增可信观察器，可读取模块、注册表、真实 CPU/对象/线程并限量 hook；默认 RVA 绑定本文安装哈希：

```powershell
python tools\d3-re\assess_runtime.py --pid <pid> --out out\windows\kbm\assessment-20261101\probe.json --name root.normallayer.consolestart_main --slots 19 --seconds 4
python tools\d3-re\assess_runtime.py --pid <pid> --out out\windows\kbm\assessment-20261101\dump.json --dump
python tools\d3-re\dis_runtime.py 0x83b70c0 --count 80
python tools\d3-re\xref_runtime.py 0x914f840 0x83baa90 --json out\windows\kbm\assessment-20261101\xrefs.json
```

xref_runtime.py 已修复旧版在 text 头扫描 12 字节即停止的问题；一次约 50 秒，应批量查询，输出为待验证候选。旧 trace_ui_all/disp/vtable 的 ARM64 host context 读法错误，trace_ui_widgets 把 CPU* 当 widget，均先停用作否定性证据。

### 4.3 游戏身份

| 项 | 值 |
| --- | --- |
| 游戏 | Diablo III: Eternal Collection，`01001B300B9BE000` |
| 版本 | `2.6.2.52309` |
| main NSO build id | `2607A74F5DF7754CC0357B5DF7E496931355D8CA` |
| `01001B300B9BE000_code.dll` SHA-256 | `A829DCE8AC2554A44DF087132CF9D266582010280C660D32A958642C8B7BDA51` |

所有地址、UI 结构、字符串偏移都绑定这个版本。

## 5. 原生 UI 已确认的事实

### 5.1 Switch 触摸屏不是原生 UI 指针

`mouse_steer=0`、`touch=2` 实测：

- “按任意键”画面可以被鼠标点击推进（任意键本来就接受任意输入）；
- 主菜单点 `继续`、`选项` **没有反应**；
- 游戏内点地面，角色**不移动**。

结论：触摸屏只是 HID 触摸，不是 PC 鼠标 UI 层。证据：`out/windows/kbm/touch/02-after-touch-click.png`、`09-click-options.png`、`11-touch-ground.png`。

### 5.2 控制台回调表不是“按键 → 菜单项”的分发器

表在 guest `0x987bf20`（`main + 0x1876f20`），条目 24 字节：

```c
struct UiEntry {          // 0x18
    const char* name;     // +0x00  guest pointer
    u32 hash;             // +0x08  djb2
    u32 pad;
    void* handler;        // +0x10  guest code pointer
};
```

`tools/d3-re/trace_ui_all.py` 按 `g_disp` 把全部 **327 条**（326 个唯一 handler）解析成真实 host 函数并 hook。当轮观察：

- 暂停菜单按 A 选择“继续”，菜单正常关闭；
- **326 个 handler 一个都没有命中**。

这支持把它作为 UI 脚本可调用函数注册表研究，不能把它当成已确认的 A 键分发器。零命中只说明当轮观测未捕获经过这些入口的事件；不能进一步证明真正鼠标事件一定走某个 VM，或已经排除所有其他调用路径。注意：按 A 零命中是人工观察，未单独落盘，见第 8.2 节。

### 5.3 UI 对象注册表（本轮最重要资产）

由 `0x8337b70` 的插入逻辑反推，运行时实测：

```text
0x914f840            // guest 全局
  -> *(u64)          // P1
  -> +0x10           // P2
  -> +0xb80          // P3
  -> *(u64)          // map
```

map 布局：

```c
u32 mask;       // +0x00  当前 8191（桶数 - 1）
u32 count;      // +0x04  条目数：菜单约 5.7k，游戏内约 19.3k
u64 buckets;    // +0x10  guest 指针，指向 bucket 数组

struct Node {   // 每个条目
    u64 next;   // +0x00
    u64 key;    // +0x08  FNV-1a 64(小写完整路径)
    u64 obj;    // +0x10  UI 对象 guest 指针
};
```

key 是 UI 路径的小写 FNV-1a 64 哈希，例如：

```text
root.normallayer.consolemainmenu_main
root.normallayer.consolepause_main
root.normallayer.consolepause_main.layoutroot.arrow_down
```

`tools/d3-re/find_ui_object.py` 会从 `runtime_rodata.bin` 里枚举候选路径、算哈希、在注册表里命中，并打印对象字段。示例：

```powershell
python tools\d3-re\find_ui_object.py --pid <pid> --prefix root.normallayer.consolemainmenu_main
python tools\d3-re\find_ui_object.py --pid <pid> --name root.normallayer.consolepause_main.layoutroot.arrow_down
```

### 5.4 UI 对象字段（已观察，未全部证实）

以 `root.normallayer.consolepause_main.layoutroot.arrow_down` 为例：

| 偏移 | 含义 | 实测值 |
| --- | --- | --- |
| `+0x00` | vtable（guest） | `0x90af208`（同一批还有 `0x90ab9d8`、`0x90adb78`、`0x90ab5f0`、`0x90ae520`） |
| `+0xc8..+0xd4` | 矩形 min/max `(x1,y1,x2,y2)` | `86, 538, 142, 581` |
| `+0xe0..+0xec` | 矩形 `(x, y, w, h)` | `86, 538, 56, 43` |
| `+0x1d0` | 指向可见文字缓冲区的候选指针 | `find_ui_text.py` 用它把可见文字映射回控件 |

重要保留：

- `scan_ui_rects.py` 的 docstring 写 `+0xd8/+0xf0`，代码实际用 `+0xe0..+0xec`；以代码和实测为准，接手后先校准一次。
- 矩形不一定是屏幕坐标。`consolepause_main` 自身是 `(0,0,960,720)`，虚拟屏按 1280×720 记录，部分对象出现负坐标或超出 1280。**做命中前必须先确认父链变换**，不能直接拿 `+0xe0` 当屏幕坐标。
- `dump_ui_children.py` 的子容器读取目前不可靠（`list-children.json` 里有大量 `access violation`），不要把它当对象树真相。
- `find_ui_text.py --text 继续` 找到 24 处字符串和若干 `+0x1d0` 指向它们的对象，但“文字 → 可点击按钮”的链路还没有闭环验证。

注册表规模参考：开始画面 5,694；主菜单 5,718；暂停菜单 19,289。用 `dump_ui_keys.py` 导出全部 key，用 `match_ui_hashes.py` 对照 rodata 验证哈希函数。

### 5.5 运行时内 guest 调用桥（可复用）

`0003-native-bridge.patch` 新增 `src/nx/runtime/native_input.c/.h`：

- 单槽队列 `native_input_queue(pc, args)`；
- 在通用 rt_poll 和 snx_svc 入口取出，复制当前 CPU，设 x0..x7、x30=0、独立 256 KiB guest 栈；当前没有 UI 主线程筛选；
- 经 `snx_lookup` 逐块执行到 `pc == 0`；
- `g_busy` 防止注入函数内部再次进入；
- 默认不执行任何东西，不改变正常启动。

调试热键（`sdl3.c`）：

| 键 | 调用 | 结果 |
| --- | --- | --- |
| F8 | `UIConsole_MainMenu_Accept(0x8366870, 0, 0)` | 返回，`steps=1`，无崩溃、无可见变化 |
| F9 | `UIHeroSelect_PlayHero(0x835c880, 0, 0)` | 同上 |
| F10 | `UIStartScreen_Console_OnButtonPress(0x836a400, 0, 0)` | 同上 |

结论仅限于：交接记录中的几个空参数调用曾返回且无可见效果，不能推出一般调用安全，也不能据此确认参数类型。真实控件/VM 上下文、消息布局和主线程归属仍需取证。

本次源码复核补充：

- rtapi.c::rt_poll 与 svc.c::snx_svc 都会取同一个队列，未验证线程身份、UI 阶段或 TLS；“在 guest 线程执行”不等于“在 UI/输入主线程执行”。
- native_input.c::native_input_run 使用共享临时栈和普通 g_busy 标记，尚不能宣称具备跨线程串行化保证。
- 到达步数上限或查找失败也会输出 returned 日志。后续必须区分真正返回、超限和错误，不能仅凭该词验收。
- SELFTEST_PC=0x8a49690 的实际代码并非注释所称的 djb2；该函数定位错误，保持禁用。不能再归因为已被本轮实测否定的“代码版本不一致”。

两个必须记住的坑：

- `SNX_NATIVE_TEST=1` 探针两次都停在“自动存档”提示（约 0.5 秒，未到 3000 帧），**没有执行**；不能据此判断 `x0=0` 可用。探针保持默认关闭。
- 把 `"A"` 写进 `g_mem + kmem_alloc 地址` 会让游戏在另一线程以 `invalid memory access` 崩溃。`kmem_alloc` 的地址不能当普通 guest 内存直接写。

## 6. 已排除路线（不要再重复做）

| # | 路线 | 结果 |
| --- | --- | --- |
| 1 | Switch 触摸屏当鼠标 UI 层 | 菜单无反应、点地面不走；只对“按任意键”有效 |
| 2 | 直接往 HID 鼠标环填数据 | 当前扫描未见 main 消费；没有已验证消费端，不作为主线 |
| 3 | 从 Frida 外部线程直接调 guest 函数 | `BEX64 0xc0000409`，崩在 JIT；必须在游戏线程 + 独立栈 |
| 4 | 把 `0x987bf20` 表当按键事件分发器 | 326 个 handler 全部 hook，按 A 零命中 |
| 5 | 全局 hook 基础对象 vtable | 每帧上万次调用，无法从计数隔离事件方法 |
| 6 | hook 控件构造函数 `0x83a1db0` / `0x83b70c0` 取控件 | 0 捕获 / 无 disp 槽 / 参数是 host 地址或错位 |
| 7 | 用左摇杆把暂停菜单焦点从右侧头像移到左侧列表 | 焦点不动；当前注入方式无法完成该操作 |
| 8 | 直接 `handler(0,0)` 产生动作 | 安全返回但无效果，缺真实控件/上下文 |
| 9 | 错误换算 fixed ELF 与 guest 地址 | 实际 text 一致；旧比较偏了 0x5000，须减真实 main 基址 0x8005000 |
| 10 | 启动早期 hook `0x83a1db0` 取 widget | 捕获 5 次，但都是无效指针/错位字段 |

另外，`0x83b7fc0` 是模拟量输入方法（`(this, 2 个 float 增量)`，更新 `+0xe0/+0xe4/+0x180/+0x184` 后经 vtable `+0xb0` 委托），不是菜单按键事件。`0x83bae20` 是“是否存在回调”的谓词。

## 7. 下一步（只做原生事件和动作层）

### P0 固定代码基线、执行线程与对象上下文

1. 核对 build id、code.dll、运行时哈希以及 g_mem / g_disp / g_code_lo 的当前 RVA，所有反汇编以匹配的 runtime dump 为准。
2. 用 find_ui_object.py 查一个指定控件，跟踪其实际事件方法、回调对象使用者、UI 根对象和输入更新点。注册表条目不等于当前可见控件。
3. 确认 UI/输入主线程、TLS、帧阶段、函数 ABI 和真实参数，再通过调用桥提交有业务效果的探针；不要继续猜 handler(0,0)。
4. 对照已知控件校准客户区、游戏视口和 UI 坐标变换。+0xe0..+0xec 的矩形只作诊断，不直接写成生产命中规则；可见性、禁用、遮挡、父子裁剪和对象生命周期尚未确认。
5. 修正或补足调用桥的线程选择、串行执行和明确的完成/错误判据，再扩大使用范围。

验收：已确认线程与上下文，且一次调用的参数和业务结果可核验；空参数返回不算完成。界面操作与视觉对照交给 Terra。

### P1 原生鼠标消息与 UI 分发

优先找 D3 的原生 UI 输入分发/控件事件方法，由游戏自己处理坐标命中和事件消费。利用特定对象缩小追踪范围，不再全局无差别 hook。

1. 先找到实际消息结构/事件码及其消费者，不照抄 D2R 的 hash、payload 或地址。
2. 先送鼠标移动，验证“继续”和“选项”的 hover；再送 down/up，验证点击、捕获/释放和滚轮。
3. 在主菜单、暂停菜单和背包验证遮挡、不可见/禁用项以及窗口缩放、黑边。
4. 带真实上下文调用业务 handler 可以帮助定位，但一次回调成功不能代替完整的鼠标事件链路。

**取消旧 P1“悬停设焦点 + 合成 A”。不发送 Npad 确认，不使用手柄光标或方向键模拟鼠标。**

验收：关闭键鼠转 Npad 与鼠标转触摸后，按指针位置的 hover/click 仍成立，并能证明事件经过游戏原生分发。

### P2 世界点击（核心验收，尽早启动调查）

已有线索：

- Power 脚本函数表在 fixed ELF module offset 0xd69d00，已解析 2,426 条；数据表与实际调用目标仍须按当前 runtime 核对。
- PowerCursorSetToOpenLocationNearCursor（guest 0x88f0c10）接受的是 cursor 索引，不能当屏幕坐标函数使用。
- UI_HUD_ClickPredicate（历史 transient 表 0x9874720，handler 0x83db4e0）需要有效 HUD 上下文；HUD 不活跃时表项可能是 0xffffffff。谓词不是移动命令。

要闭环的是：鼠标屏幕点 → 游戏场景拾取/世界点或目标 → 游戏自己的移动、交互和定点技能入口。不能用推杆、自行导航或按 A 代替。UI 部分验证通过不能降低世界输入的验收要求，不必等 UI 全做完才开始调查。

验收：点城镇两个不同空地点，松开鼠标后角色仍去对应目的地，障碍处理遵循游戏原生规则；点 NPC/物品/出口完成正确目标交互，技能使用鼠标目标。全程无键鼠生成的 Npad。

### P3 键盘走游戏动作层

ActionBinding 描述和 UI_Key_Binded 是定位线索；先确认有活跃代码消费它们。Tab/I/M/1–4/Esc 按实际绑定走动作层，单独验证按下/抬起、修饰键和文本输入；禁用旧键盘转 Npad 后仍须成立。

### P4 路由、稳定性与交付

验证游戏 UI/世界/F2 菜单的事件消费、失焦释放、窗口/全屏与缩放、控件销毁重建，连续操作 30 分钟。具体判据见 [KEYBOARD-MOUSE.md](KEYBOARD-MOUSE.md)。仅 UI 成功时报告“原生 UI 部分验证”，不回退到映射走位。

D2R 只借鉴原生消息和共享动作入口的研究方式。其当前源码也含手柄路径，且 dm_world.c 明确不把空地点按作为移动；不能由它保证 D3 点地走位。来源与本次核对说明见 [方案第 3 节](KEYBOARD-MOUSE.md#3-d2r-参考的正确用法)。

### 不安排的工作

- A+ 的键位配置、鼠标转摇杆、翻滚映射、虚拟手柄，以及“设焦点 + 合成 A”。
- 根据字符串/矩形字段直接宣布完整 PC 输入层存在，或把菜单一次回调成功当原生键鼠完成。
- 优先整体替换 PC 布局；先确认输入路径。若平台裁剪确实阻断鼠标处理，再评估必要的布局/代码适配。
- 直接删除 0002：0003 依赖其上下文。历史实现若后续清理，须重新生成补丁和哈希并验证构建；本次未改这些文件。

## 8. 工作区与提交状态

### 8.0 本次方法评估修订

本次提交包含 AGENTS.md、原生方案/交接/证据与方法评估、工具 README、assess_runtime.py 和修复后的 xref_runtime.py。基线仍为 2242387，修订后的提交号使用 git log -1 查看，避免在提交内部记录自身哈希。

实测已确认 ELF/运行时一致、旧 hook ABI 错误、旧 xref 只扫描 12 字节、新探针可读取真实 guest 对象。主菜单与城镇未验收。原始 JSON、dump 和截图位于 out/windows/kbm/assessment-20261101/，被 git 忽略；关键结论与数值已写入本次报告。以下 8.1–8.4 保留原交接时的历史状态，不能当作本次提交后的实时 git status。

README、STATUS、Android/Windows 发行构建等无关工作区改动不纳入本次提交。自动生成的 .serena 配置/缓存及其他未修改的旧探针也不混入；如后续要整理，单独审查。



### 8.1 已提交

分支 `feat/d3-native-kbm`，最后提交 `2242387 windows: execute real UI handlers through the runtime bridge`，**没有 upstream**。

标签（按时间）：

```text
kbm-b0  kbm-b1a  kbm-b1b-checkpoint  kbm-b1b-script-table
kbm-aplus1  kbm-b2-bridge  kbm-aplus2
kbm-b3-runtime-code  kbm-b3-disp-trace  kbm-b3-ui-table
kbm-b3-probe  kbm-b3-vtable  kbm-b3-vtable-trace  kbm-b3-widgets
kbm-b3-input-method  kbm-b3-native-call
```

补丁状态：`Apply-Patches.ps1 -CheckOnly` 通过，0001/0002/0003 已应用。

### 8.2 未提交的新工具（本轮产物）

绝大多数在 `tools/d3-re/`，另有一个启动脚本，均未 `git add`：

| 文件 | 作用 |
| --- | --- |
| `trace_ui_all.py` | 解析并 hook 全部 327 条控制台 UI 表项（326 个唯一 handler，经 `g_disp`） |
| `dump_ui_objects.py` | 读 UI 对象注册表，打印 key/对象/vtable/字段 |
| `dump_ui_keys.py` | 导出注册表全部 key（哈希） |
| `find_ui_object.py` | 按 FNV-1a 路径名查对象并 dump 字段 |
| `find_ui_text.py` | 按可见文字反查持有它的对象（看 `+0x1d0`） |
| `scan_ui_rects.py` | 全表扫描，筛出有合理矩形/落在指定区域的对象 |
| `dump_ui_children.py` | 尝试读子容器；**目前不可靠** |
| `match_ui_hashes.py` | 用 rodata 字符串验证注册表 key 的哈希函数 |
| `probe_uimap.py` | 打印 map 头和 bucket 布局 |
| `probe_map_entries.py` | 最小化枚举 map 条目 |
| `probe_gmem.py` | 通过 `g_mem` 读几个关键 guest 地址 |
| `probe_guest_range.py` | 打印 `g_mem` 背后的 host range |
| `dis_runtime.py` | 对 `runtime_text.bin` 按 guest 地址反汇编 |
| `xref_runtime.py` | 在运行时 text 里扫 ADRP+ADD/LDR 引用 |
| `tools/windows-dev/Launch-Background.ps1` | 小窗口、后台、非置顶启动 |

`out/windows/kbm/touch/` 是本轮取证目录（截图 + 文本日志），包括 `trace-all.log`、`pause-rects2.txt`（3,349 个有矩形的对象）、`pause-objects.txt`、`mainmenu-objects2.txt`、`ui_keys_intro.json` 等。注意 `trace-all.log` 只记录了“hook 就绪”，按 A 零命中是当轮人工观察，没有单独落盘。

### 8.3 未提交但**不是**本轮改的

`git status` 里还有 8 个已跟踪文件的修改：

```text
README.md
docs/STATUS.md
docs/STRUCTURE.md
docs/android/BUILD.md
docs/windows/BUILD.md
docs/windows/RELEASE.md
patches/windows/0001-fsr1-present-stats.patch
tools/windows-dev/package_fsr_release.py
```

内容看起来是更早的文档 / 发行修订：README 增加了 KEYBOARD-MOUSE 链接并更新安装入口，STATUS/RELEASE 更新安装位置，0001 补丁有大段重排。它们不一定属于本次 UI 逆向，**不要和键鼠逆向混在一个提交里**，提交前逐项确认。

### 8.4 未跟踪的 `snx-src/`

`snx-src/ScarletNX-FSR1` 是 2026-10-21 解出的源码快照，被 `键鼠支持调研与方案.md` 引用；它**不是**当前构建源：

- 有 `mouse_steer`（0002），但没有 `src/nx/runtime/native_input.c`（0003）；
- 没有 `.git`，`git -C` 会走到主仓库；
- 当前构建源是 `reference/ScarletNX-src`。

建议删除或加入 `.gitignore`，不要提交。`键鼠支持调研与方案.md` 里的相对链接指向这个快照，接手时以 `reference/ScarletNX-src` 为准。

## 9. 常用命令

```powershell
# 以下界面操作交由 GPT-6.1 Terra 子代理执行。
# 原生探针：关闭历史鼠标映射与触摸；键盘旧映射仍需另行隔离。
$nativeProbeArgs = @('--fullscreen=0', '--docked=0', '--resolution=1', '--mouse_steer=0', '--touch=0')
.\tools\windows-dev\Launch-Background.ps1 -GameArgs $nativeProbeArgs

# 发送宿主键鼠事件本身不证明原生路径；记录实际消费者。
.\tools\windows-dev\Post-GameInput.ps1 -Key space
.\tools\windows-dev\Post-GameInput.ps1 -Click '600,120'   # 窗口客户区坐标
.\tools\windows-dev\Post-GameInput.ps1 -Move '600,200'

# 抓图
.\tools\windows-dev\Capture-Screen.ps1 -OutPath out\windows\kbm\touch\screen.png
.\tools\windows-dev\Capture-Window.ps1 -ProcessId <pid> -OutPath out\windows\kbm\touch\window.png

# 运行时取证
python tools\d3-re\dump_runtime_code.py --pid <pid> --out out\windows\kbm\b2\runtime
python tools\d3-re\trace_ui_all.py --pid <pid> --seconds 25
python tools\d3-re\find_ui_object.py --pid <pid> --prefix root.normallayer.consolepause_main
python tools\d3-re\scan_ui_rects.py --pid <pid> --region 68,243,468,553

# 静态分析（运行时 dump）
python tools\d3-re\dis_runtime.py 0x83b70c0 --count 80
python tools\d3-re\xref_runtime.py 0x8dcf212

# 补丁检查
.\patches\windows\Apply-Patches.ps1 -CheckOnly
```

Frida 脚本会 attach 到已运行的进程；用 `--pid` 指定。大多数探针默认只读，不会写存档或改 `_code.dll`。

## 10. 风险与注意事项

1. **版本绑定**：所有地址、偏移、UI 结构只对 `2.6.2.52309` / 当前 `_code.dll` / 当前 `scarletnx.exe` 成立。换版本必须重做 build id、`g_mem` dump、表偏移和对象字段。
2. **符号偏移会变**：改运行时源码后，`g_mem` / `g_disp` / `g_code_lo` 的 RVA 要重新用 `llvm-nm` 取；所有硬编码这些值的工具（`trace_ui_all.py` 等）都要同步改。
3. **调用桥仍是最小探针**：外部线程直接调 guest 曾崩溃；当前通用 guest 入口未筛选 UI 主线程，g_busy 也不等于跨线程串行化。先完成 P0，不把空调用返回当安全性证明。
4. **`kmem_alloc` 地址不能当 guest 内存写**：已实测 `invalid memory access`。
5. **矩形坐标未校准**：在做 P0 之前，不要基于 `+0xe0` 写生产逻辑；先拿一个已知按钮对截图校准。
6. **暂停菜单是特殊场景**：焦点在右侧头像，左摇杆/方向键注入都不移动。做 UI 点击验收优先用主菜单，再处理暂停菜单。
7. **SNX_NATIVE_TEST 保持未设置**：历史运行在探针入队前停于“自动存档”，不能据此认定探针导致卡住。当前源码按变量是否存在启用，设置为 0 也会启用。
8. **强杀进程会留下自动存档提示**：下次启动可能停在提示上，不是新 bug。
9. **`out/` 不进 git**：截图、运行时 dump、构建产物只在本机；如果交接是“换机器”，这些证据需要单独拷贝或重新生成。
10. **只验收原生路径**：A+ 退出后续开发和交付。原生探针关闭鼠标转 Npad 与触摸；键盘验收也须隔离旧映射。未完成则如实记录缺口，不用 A+ 补交。

## 11. 文件索引

| 路径 | 内容 |
| --- | --- |
| `docs/windows/KEYBOARD-MOUSE.md` | 原生唯一方案、方向复核、证据边界、原生探针与验收 |
| `docs/windows/KBM-RE-EVIDENCE.md` | 第 1–15 节逐轮 RE 证据（B0 → B3） |
| `docs/windows/KBM-HANDOVER.md` | 本文 |
| `patches/windows/0002-mouse-steer.patch` | 历史 A+ 鼠标映射；停止推进，原生探针关闭 |
| `patches/windows/0003-native-bridge.patch` | guest 最小调用桥及触摸门控；线程/上下文仍待完善 |
| `patches/windows/base.json` | 补丁哈希、结果文件哈希、基线提交 |
| `tools/d3-re/` | Frida / 反汇编 / UI 对象探针 |
| `tools/windows-dev/Launch-Background.ps1` | 小窗后台启动 |
| `tools/windows-dev/Post-GameInput.ps1` | 无焦点 PostMessage 键鼠 |
| `out/windows/kbm/b0` | NSO、ELF、Ghidra 产物 |
| `out/windows/kbm/b1` | UI 表、脚本表、PC UI 表 JSON |
| `out/windows/kbm/b2` | 运行时 text/rodata/data dump、A+ 验收截图 |
| `out/windows/kbm/touch` | 本轮触摸/UI 对象取证 |

## 12. 接手检查清单

- [ ] 确认分支 feat/d3-native-kbm、git log -1 和本次提交范围（见 8.0），保留无关工作区改动。
- [ ] `Apply-Patches.ps1 -CheckOnly` 通过；安装 exe 的 SHA-256 与 `build-kbm` 一致。
- [ ] 开始前先激活 Serena；确认只做原生键鼠；不复验或完善 A+。探针按 3.3/9 节显式关闭鼠标映射与触摸，键盘另隔离旧映射。
- [ ] 跑一次 `find_ui_object.py --prefix root.normallayer.consolemainmenu_main`，确认注册表可读。
- [ ] 完成 P0 的代码基线、线程/上下文确认和坐标校准，再验证原生 UI 消息与世界点击。
- [ ] 未验证的业务注入保持关闭，分项记录原生 UI/世界/键盘结果；不以手柄映射充当交付。
