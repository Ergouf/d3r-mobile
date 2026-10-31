# D3 原生键鼠：RE 证据（B0）

日期：2026-10-31。范围：Windows ScarletNX 运行时。B0 只做地址基线和探针，不改游戏/运行时。

## 1. 输入身份

| 项 | 值 |
| --- | --- |
| 游戏 | Diablo III: Eternal Collection，`01001B300B9BE000` |
| 游戏版本 | `2.6.2.52309` |
| main NSO build id | `2607A74F5DF7754CC0357B5DF7E496931355D8CA` |
| `main.nso0` SHA-256 | `B6487A316F8BF5B92D26C07C5E9A75AA4654CF325E2EAF033A083253D511F267` |
| `01001B300B9BE000_code.dll` SHA-256 | `A829DCE8AC2554A44DF087132CF9D266582010280C660D32A958642C8B7BDA51` |
| `libd3guest.so` SHA-256（Android 参考镜像） | `DD050EF63CBAEAAEAE9F7C842B26456A05D7482AAF9B91103A9BF0E0188625A2` |
| `d3_main.elf` SHA-256（B0 生成物） | `3E35731A5FADA4BF1B276F42E704FAD40C2D7AE3D436B283947817B634998320` |

## 2. 运行时 guest 模块

Frida 通过 `01001B300B9BE000_code.dll!snx_module` 读取：

| 模块 | guest base | size | text | rodata | data |
| --- | --- | --- | --- | --- | --- |
| `rtld` | `0x8000000` | `0x4000` | `0x1a00` | `0xd20` | `0x280` |
| `main` | `0x8005000` | `0x1aa7000` | `0xc72b90` | `0x4249c4` | `0xc4a14` |
| `sdk` | `0x9aac000` | `0xcfb000` | `0x5407d0` | `0x6985e8` | `0x61fb0` |

`snx_module.abi = 11`。

guest 内存在宿主进程里是**视图拷贝**，不是直接映射到 `0x8005000`。B0 的定位方法：

1. 读 `SnxModInfo.main.base/size`；
2. 找 `Process.enumerateRanges('rw-')` 中 `size == main.size` 的视图；
3. 视图基址 + NSO 偏移 = 宿主地址；该偏移同时就是 **guest offset**（对 main 而言）。
4. `guest_address = main.base + offset`。

## 3. 已定位的 PC 输入/UI 字符串

通过 Frida 扫描 main 视图确认，值均为原始字符串：

| 字符串 | guest address | NSO 文件偏移 |
| --- | --- | --- |
| `LeftClickToMove` | `0x8dc985b` | `0xdc495b` |
| `RightClickAttack` | `0x8e26e0b` | `0xe21f0b` |
| `UseCommandClickAsRightClick` | `0x8e4533b` | `0xe4043b` |
| `UI_HUD_ClickPredicate` | `0x8dcf212` | `0xdca312` |
| `ControlScheme` | `0x8dc91cb` | `0xdc42cb` |
| `ActionBinding` | `0x8ecc112` | `0xec7212` |

`ActionBinding` 后面紧接 protobuf 描述：`key_1`、`key_modifier_flags_1`、`key_2`、`key_modifier_flags_2`，说明 Switch 包里保留了 PC 键位绑定的数据结构。

## 4. 重要负结果

D3 的 main 模块**没有**导入/调用 `GetMouseStates` / `GetKeyboardStates`：

- `guest_relocs.h` 的 main 导入只有 Npad、SixAxis、swkbd 等；
- `main.nso0` 的字符串表没有 `GetMouseStates`；
- `libd3guest.so` 里有 SDK 的 `GetMouseStates` 实现，但 main 没有直接 BL 调用，也没有对应导入槽。

因此：

- **不要**把 `hid.c:430` 的全零鼠标环当成主路径；
- 原生键鼠必须走 **UI 消息注入**、**游戏动作/点击入口**，或把游戏切到 PC 控制模式；
- D2R 的 `dm_cursor.c` / `dm_world.c` 是正确参照。

## 5. 工具与复现

```powershell
# 1) 解 NSO（用户自备 hactool）
hactool -t nso --uncompressed=main.bin main.nso0

# 2) 生成 Ghidra 可加载 ELF
python tools/d3-re/build_main_elf.py main.bin --out out/windows/kbm/b0/d3_main_fixed.elf

# 3) Frida 读 guest 字符串（spawn 一个临时进程，读完即杀）
python tools/d3-re/frida_probe.py --json

# 4) Ghidra（8G 堆）
.\tools\d3-re\ghidra_analyze.ps1 -Elf .\out\windows\kbm\b0\d3_main_fixed.elf `
  -GhidraHome <ghidra_12.1.4_PUBLIC> -JavaHome <jdk-21>
```

B0 验收：`frida_probe.py --json` 能打印上表 guest 地址和字符串值；`d3_main_fixed.elf` 能被 `llvm-readelf` 识别为 AArch64 ELF。

## 6. 未完成 / B1 入口

- Ghidra 全量分析在 8G 堆下仍在跑；若某函数导致卡住，改用定向分析或缩小函数范围，不能把“分析超时”当成“功能不存在”。
- B1 要找：
  - Npad polling → action mapping；
  - `LeftClickToMove` / `RightClickAttack` 的动作分发；
  - UI 根控件/消息处理；
  - 键盘动作/文本输入。
- 下一步是只读探针：先读全局/函数指针，不写游戏内存。

## 7. B1：UI 回调注册表（已定位）

运行中的 UI 回调表在 guest `0x987bf20`（`main.base + 0x1876f20`，BSS），宿主视图偏移 `0x1876f20`。条目 24 字节：

```c
struct UiEntry {          // 0x18 bytes
    const char* name;     // +0x00, guest pointer
    u32 hash;             // +0x08
    u32 pad;
    void* handler;        // +0x10, guest code pointer
};
```

已确认：

- `FUN_00a49790` 是名字哈希：`h = h * 0x21 + c`（djb2，32 位）。
- `FUN_003c9a70` 是启动时的表初始化器，写入 `0x1876f20` 起的条目。
- `FUN_003cc5c0` 按名字哈希查表并返回 handler；调用者是 `FUN_0039ceb0` 和 `FUN_003b1e70`。
- `FUN_0039ceb0` 把两个回调 handler 存到 widget 的 `+0xa8` / `+0xb0`；`FUN_003b1e70` 是 UI 更新/分发的候选。
- 例：条目 1 `UIStackSplit_Console_OnAccept` 的 handler 是 `FUN_0022dc30`（guest `0x8232c50`）。
- 运行时导出 328 条：`UIStackSplit_Console_*`、`UIConsole_MainMenu_*`、`UIInventory_*`、`UIHeroSelect_*` 等。
- 当前表里**没有** `UIGameMenu_*` / `UIStartScreen_*` 这类 PC 回调；说明这个表是 Console UI 的注册表，PC 布局/回调需要 B7 再确认。

复现：

```powershell
python tools/d3-re/dump_ui_table.py --json out/windows/kbm/b1/ui_table.json
```

## 8. 地址基线修正（B1b，重要）

之前的 `d3_main.elf` 直接从带 `0x100` 字节 NSO 头的镜像构建，导致：

- Ghidra 代码地址 = 真实 guest 地址 **+0x100**
- Ghidra 反编译里的字符串整体偏移，字符串引用可能指向错误的字节
- 旧文档里的函数地址不能直接当作 guest 地址

已修正 `tools/d3-re/build_main_elf.py`：按 NSO 头解析 `text/ro/data` 的 `file_off` 与 `mem_off`，生成：

- `out/windows/kbm/b0/d3_main_fixed.elf`
- SHA-256 `B397AF8FC1389A30B8D051DE524E0DA83B4E03345604EBAB4376A34CF20D9DB0`
- 新 Ghidra 项目 `D3MainFixed`，分析完成：`2273` 条相关字符串、`2942` 条引用

修正后的地址关系：

```text
Ghidra 地址 = guest 模块内偏移
绝对 guest 地址 = 0x8005000 + Ghidra 地址
```

例：

- `FUN_003bad24` → 绝对 guest `0x83bad24`
- `FUN_003b9820` → 绝对 guest `0x83b9820`
- UI handler `0x81fb910` → Ghidra `0x1fb910`

## 9. B1b 新发现

### 9.1 `LeftClickToMove` 只是字符串表条目

修正后 Ghidra 中只有一处引用：

```text
STRING 0xdc485b "LeftClickToMove"
  REF 0x4e3154  FUN_004d5380
```

`FUN_004d5380` 是全局字符串表初始化器，把 `LeftClickToMove` 以 ID `0x6d7` 注册：

```c
FUN_004e5e50(3, 2, 0x6d7, 0x3f, "LeftClickToMove", 2);
```

结论：`LeftClickToMove` 不是动作函数入口，直接找字符串 xref 找不到动作分发。

### 9.2 `UI_HUD_ClickPredicate` 的运行时表项

`UI_HUD_ClickPredicate` 在 guest `0x8dcf212`。运行时在 PC UI 表里找到一条 24 字节表项：

```text
guest 0x9874720:
  +0x00 name    = 0x8dcf212  "UI_HUD_ClickPredicate"
  +0x08 hash    = 0x908be1d4  (djb2)
  +0x10 handler = 0x83db4e0
```

该表项所在表是**临时/按屏幕存在**的：HUD 不活跃时，同一地址会变成 `0xffffffff` 空桶标记。表项格式与 Console UI 表相同（24 字节 `{name, hash, handler}`）。

`0x83db4e0` 不是函数入口，而是 `FUN_003dafb0` 内部的一个 continuation block（状态机/命令块），依赖调用方预置的 `x19/x20` 等寄存器。不能直接当普通函数调用。

同表后续条目还有：

- `UI_InvOpen_OnClick` handler `0x83db500`
- 其他若干 UI 命令/字符串

这说明游戏确实有 **PC UI 命令/回调表**，`UI_HUD_ClickPredicate` 是其中一个命令/回调。

### 9.3 `%s_Mouseover` 是控件状态路径，不是鼠标分发

`%s_Mouseover` 在 guest `0x8dc41be`，引用在 `FUN_003f6470`。该函数实际构造：

```c
"Tab_Stash%02d"
"%s_Unselected"
"%s_Mouseover"
"%s_Selected"
```

然后调用 `FUN_003a2c40(widget, unselected, mouseover, selected)` 设置控件的三种视觉状态路径。它是**控件状态路径设置器**，不是鼠标事件处理器。

### 9.4 动态输入与 UI 状态机

- `PostMessage(WM_KEYDOWN/UP)` 到游戏窗口可以稳定驱动 UI，即使窗口不在前台。
- 物品栏的 `UIInventory_OnButton1`（guest `0x81fb910`）是 `FUN_001fb4d0` 内部的状态机 continuation block，任意按键都会进入同一个块。
- 抓到调用链（按最近的 AOT 入口映射）：

```text
0x81fb910  (handler block)
  <- 0x83bad24 附近
  <- 0x83bae00 附近
  <- 0x8331d50
  <- 0x82b9120
  <- 0x82b9724
  <- 0x8046650
  <- 0x84cda68
  <- 0x8005a1c
```

- `FUN_003b9820(key, player)` 比较键码与玩家绑定字段 `+0x134c/+0x135c/...`。
- `FUN_003b8630` 遍历 `DAT_0186ef50 + 0x30` 的按键事件链表并调用 `FUN_00419c80`。
- 这条链属于**按键绑定/设置界面**，不是世界动作执行层。

### 9.5 CPU / JIT dispatch 探针

- `CPU.mem` 偏移 `0x350`，是 guest 地址 0 的宿主基址；`mem + 绝对 guest 地址` 可读模块内存。
- `CPU.disp` 偏移 `0x358`，`code_lo/code_hi` 偏移 `0x360/0x368`，可查任意 guest 地址当前实际 host 函数。
- 已确认 `0x81fb910`、`0x8366870`、`0x81fb920` 等 UI handler 是 AOT 函数。
- `FUN_0039cdb0`（旧名 `FUN_0039ceb0`）与 `FUN_003cc4c0`（旧名 `FUN_003cc5c0`）在当前运行中 `disp = 0`，说明它们没有被编译/执行，可能是未使用或已内联路径。

### 9.6 Power 脚本函数表（已定位）

在 fixed ELF 的 module offset `0xd69d00` 找到脚本函数表，条目 `0x30` 字节：

```c
struct ScriptFn {          // 0x30 bytes
    u32 name_off;          // +0x00, module-relative string offset
    u32 pad;
    u64 runtime_slot;      // +0x08, BSS slot, filled with absolute function ptr
    u32 flags;             // +0x10, 0x403
    u32 pad;
    u64 func_off;          // +0x18, module-relative function offset
    u64 next_name_slot;     // +0x20
    u32 flags2;            // +0x28, 0x403
    u32 pad;
};
```

函数绝对地址：

```text
guest = 0x8005000 + func_off
```

当前解析到 `2426` 条有效条目。已确认的关键函数：

| 名称 | func_off | 绝对 guest |
| --- | --- | --- |
| `PowerCursorSnapToGround` | `0x8ea220` | `0x88ef220` |
| `PowerCursorSetToActor` | `0x8ea4c0` | `0x88ef4c0` |
| `PowerCursorSetToOpenLocationNearActor` | `0x8ea8e0` | `0x88ef8e0` |
| `PowerCursorSetToOpenLocationNearCursor` | `0x8eac10` | `0x88f0c10` |
| `PowerCursorSetToLeftStick` | `0x914370` | `0x8919370` |
| `PowerCursorSetToRightStick` | `0x9143e0` | `0x89193e0` |

`PowerCursorSetToOpenLocationNearCursor` 的反编译签名：

```c
// 2 args:  (int cursorIndex1, int cursorIndex2)
// 3 args:  (int cursorIndex1, int cursorIndex2, actor)
int func(arglist);
// -> FUN_009c3f50(index1, index2, actor_or_0)
```

它内部按索引查 `+0x170` 的 cursor 数组（数量在 `+0x180`），不是直接吃屏幕坐标。因此它更接近“把光标设到两个 cursor 附近的空地”，不是“鼠标点地面”。

脚本参数对象格式（`FUN_00b196e0` / `FUN_00b19f80` / `FUN_00b1a2b0`）：

```c
struct ScriptArgList {   // x0
    u64 unk0;            // +0x00
    u64 unk8;            // +0x08
    ScriptArg* begin;    // +0x10
    ScriptArg* end;      // +0x18
};
struct ScriptArg {       // 16 bytes each
    double number;       // +0x00
    u32 type;            // +0x08, 3 = number
    u32 pad;
};
// argc = (end - begin) / 16
```

这意味着可以构造参数对象直接调用这些脚本函数；但 `SetToOpenLocationNearCursor` 的两个整数是 **cursor 索引**，不是屏幕坐标。

工具：

```powershell
python tools/d3-re/dump_script_table.py --filter Cursor
```

## 10. 下一步（B1b 剩余 / B2 入口）

1. 找 PC UI 命令分发器：`UI_HUD_ClickPredicate` 表项由谁调用、如何准备 `x19/x20` 和事件参数。
2. 追 `FUN_003dafb0` 的状态机入口，确认 `0x83db4e0` 的调用条件；目标是用 UI 命令注入一次“HUD 点击”。
3. 利用已定位的脚本函数表，构造 `ScriptArgList` 调用 `PowerCursor*` 函数，验证 Power cursor 是否可设置、是否能触发角色移动/交互。
4. 找屏幕坐标 → world/cursor 的转换函数；`SetToOpenLocationNearCursor` 的两个整数是 cursor 索引，不能直接当鼠标坐标。
5. 找 `LeftClickToMove` 的 action binding 表：它是字符串 ID `0x6d7`，动作表可能存 ID/哈希，而不是字符串指针。
6. 完成后进 B2 的 `input_native=0` 运行时骨架。

## 11. 安全

- 未写存档、未改 `_code.dll`、未改安装目录 exe。
- Frida 探针默认 spawn 后 kill；`--keep` 才会留下进程。
- 所有二进制分析产物在 `out/`（git-ignored）。

## 12. B2 前置：UI 回调边界与外部调用失败（2026-11-01）

### 12.1 UI 回调是状态机 continuation

`UIConsole_MainMenu_Accept`（guest `0x8366870`）、`UIStartScreen_Console_OnButtonPress`（`0x836a400`）、`UIHeroSelect_PlayHero`（`0x835c880`）在 fixed ELF 中反汇编后都落在函数中段：

- `0x836870` 处是 `stlxr`，前面没有 prologue；
- `0x836a400` 处直接读 `[x19,#0x1394]`，依赖调用方预置 `x19`；
- 它们是 UI 脚本 VM（`FUN_003dafb0` 一类）内部的 continuation block，不是可普通调用的函数入口。

结论：不能把表里的 handler 当 `void (*)(void*)` 直接调用；必须经过 UI VM 的事件分发，或找到 VM 的入口/上下文。

### 12.2 外部线程调 guest 函数会崩

`tools/d3-re/call_guest.py` 会复制 live CPU、设置 `pc/x0..x7/x30/sp`，再经 `CPU.disp` 逐块执行。用它从 Frida 线程调用纯函数 `FUN_00a49790`（djb2）时，游戏以：

```text
BEX64, 0xc0000409, faulting module unknown, offset 0x20421f7ca11
```

崩在 JIT 代码。原因是没有在游戏线程、没有合法 guest 栈/TLS，且 `cpu.thread` 指向另一个正在运行的 KThread。

结论：注入桥必须：

1. 在游戏线程上执行（例如 SVC 处理入口）；
2. 用 `kmem_alloc` 分配的独立 guest 栈；
3. 复制当前线程 CPU（保留 `tpidrro`/`thread`）；
4. 设置递归保护，避免注入函数内部的 SVC 再次触发注入。

### 12.3 工具

- `tools/d3-re/find_xrefs.py`：fixed ELF 的 AArch64 xref 扫描（ADRP+ADD/LDR、ADR、BL/B），已用 `LeftClickToMove` 的已知 xref `0x4e3154` 验证。
- `tools/d3-re/call_guest.py`：外部 guest 调用探针（仅用于确认边界，不用于正式注入）。
- `tools/windows-dev/Post-GameInput.ps1`：向游戏窗口 PostMessage 键鼠，不需要前台；方向键带 extended 标志。
- `tools/windows-dev/Capture-Window.ps1`：`PrintWindow` 抓窗口，不抢焦点；Vulkan 窗口可能返回旧帧，状态确认以桌面抓图为准。

### 12.4 构建环境

- 仓库路径 `D:\workspace\Diablo(fegnjl)` 含括号，`settingsgen` 的 cmd 命令行会被截断；用 junction `D:\workspace\Diablo-kbm` 构建。
- OpenSSL 外部工程在 `-j18` 下会因依赖文件竞争失败；用 `make -j1 build_libs` 补跑后，整体构建可继续。
- 构建产物：`out/windows/build-kbm/scarletnx.exe`。

### 12.5 A+ 鼠标层（interim，不是原生 PC 输入）

已在 `0002-mouse-steer.patch` 实现并验证：

- `mouse_steer=1`：鼠标相对窗口中心的方向和距离驱动 1P 左摇杆；左键 A、右键 B、中键 X、侧键 Y/L；开启时鼠标不再当触摸屏。
- 主菜单：左键确认“继续”，进入第一章角色（截图 `out/windows/kbm/b2/15-after-postclick.png`、`16-ingame.png`）。
- 游戏内：鼠标移到右下，角色向东南移动（`27-mouse-se.png`）。
- 暂停菜单：B 可关闭；但菜单导航是 D-pad 边沿触发，持续偏转的左摇杆只能移动一格，鼠标不能像指针一样逐项选择。这是 A+ 的硬限制，也是继续做原生 UI 注入的理由。

原生 B3 仍缺：UI VM 的事件入口/上下文，以及运行时内游戏线程调用桥。A+ 只作为可玩兜底，不算原生交付。

## 13. B2：运行时内 guest 调用桥（2026-11-01）

### 13.1 设计

新增 `runtime/native_input.c/.h`：

- `native_input_queue(pc, args)` 把一次 guest 调用放进单槽队列；
- `native_input_run(c)` 在**游戏线程**的 `rt_poll` 里取队列，复制当前 `CPU`，设置 `x0..x7`、`x30=0`、独立 guest 栈，然后经 `snx_lookup` 逐块执行到 `pc==0`；
- `g_busy` 防止注入函数内部的 SVC/分支再次进入；
- 栈由 `kmem_alloc(256 KiB, MS_STACK, PERM_RW)` 分配。

`rt_poll` 在生成代码的后向分支上被调用，是游戏线程上可用的安全点；`snx_svc` 也加了同样的入口，但实测游戏的 AOT 代码直接走 `g_svc64`，不经过 `snx_svc`。

### 13.2 实测结果

- 桥初始化成功：`native: bridge ready (stack 138003ff00)`。
- 600 帧后排队自检，桥在游戏线程执行，`steps=1` 返回，游戏没有崩溃：
  `native: djb2 self-test 09a65438 (want 908be1d4)`。
- 说明调用链（队列、游戏线程、CPU 复制、独立栈、`snx_lookup`）已跑通，但 `0x8a49690` 这个入口的返回值与预期 djb2 不符，自检目标还需要确认；不能据此宣称 UI 调用已可用。
- 另一次测试把 `"A"` 写进 `g_mem + kmem_alloc 地址`，游戏在另一线程以 `invalid memory access` 崩溃；`kmem_alloc` 的地址不能直接用 `g_mem[]` 当普通 guest 内存写。

当前 `native_input_tick()` 是空实现，桥保持休眠，不影响默认启动和 A+ 鼠标层。

### 13.3 触摸与鼠标冲突

`mouse_steer=1` 且 `touch=2` 时，左键会同时被 SDL 触摸路径送给游戏，主菜单上表现为“点角色 → 英雄资料”，而不是 A 确认。已在 `sdl3.c` 里让 `mouse_steer` 关闭 `SDL_EVENT_FINGER_*`，并把 `touch` 设为 0 或保持 2 都不再触发触摸；左键恢复为 A，主菜单“继续”可正常进入游戏。

### 13.4 代码地址基线不一致（重要）

用 Frida 读运行时 `g_mem`（`snx_module` 的 `main.base` 为 `0x8005000`）后确认：

- `g_mem + 0x8dcf212` 是 `"UI_HUD_ClickPredicate"`，字符串地址与文档一致；
- `g_mem + 0x8a49690` 的字节是 `e1 03 15 32 ...`，**不是** fixed ELF 在 `0xa49690` 的 djb2（`09 00 40 39 ...`）；
- `g_mem + 0x8366870` 是 `sub sp, sp, #0x160` 的函数序言，而 fixed ELF 在 `0x366870` 是 `stlxr` 中段指令。

结论：**fixed ELF 的代码段与当前安装的 `_code.dll` 的 guest 代码不对应**（rodata 字符串对应，text 不对应）。因此第 9 节里“UI handler 是 continuation block”的结论需要从运行时 `g_mem` 重新反汇编确认；之前基于 ELF 的代码地址不能继续用于调用目标。下一步应先从运行时 dump 一段 `g_mem` 代码，或确认 `local/assets/exefs_update/main.nso0` 与安装的 `_code.dll` 是同一版本，再重建 ELF。

### 13.5 开始菜单点击已验收

`mouse_steer=1`、`touch=2`、`0003` 的触摸门控生效后：

1. 启动游戏，片头结束后在“按任意键”画面左键一次 → 进入主菜单，`继续` 被选中；
2. 再左键一次 → 读条进入新崔斯特姆（第一章），没有出现“英雄资料”弹窗。

截图：`out/windows/kbm/b2/70-click1.png`（主菜单）、`71-click2.png`（新崔斯特姆）。这仍是 A+（鼠标→A/左摇杆）路径，不是原生 PC UI 点击。

## 14. 运行时代码 dump 与 UI handler 重新分析（2026-11-01）

### 14.1 工具

`tools/d3-re/dump_runtime_code.py --pid <pid> --out out/windows/kbm/b2/runtime` 经 Frida 从运行时 `g_mem`（`snx_module` 的 `main.base` 加上各段偏移）直接 dump：

- `runtime_text.bin`（13,052,816 字节，guest `0x8005000`）；
- `runtime_rodata.bin`；
- `runtime_data.bin`；
- `runtime_info.json`。

`g_mem` 的符号偏移按当前 `scarletnx.exe` 取（`llvm-nm ... | findstr " g_mem$"`，本次 `0x17aef20`）；换构建要重取。

### 14.2 结论：UI handler 是可调用函数

运行时 `0x8366870`（`UIConsole_MainMenu_Accept`）的实际代码：

```text
0x8366870  sub sp, sp, #0x160
0x8366874  stp x28, x23, [sp, #0x120]
...
0x8366888  mov w19, w1          ; 第二参数（玩家/按钮）
0x836688c  bl #0x8170130
0x83668ac  bl #0x832d180
0x83668e0  ...
0x8366924  br x8                ; 按 [ctx+0x1e0] 的状态跳转
```

它是**真正的函数入口**，不是状态机中段。第 12.1 节“handler 是 continuation block”的结论来自与运行时不一致的 fixed ELF，应作废；以本节和 `g_mem` dump 为准。

UI 表仍然有效：`0x987bf20` 的条目 6 是 `UIConsole_MainMenu_Accept`，handler `0x8366870`，24 字节一条。

### 14.3 当前阻塞

在 AOT entry 上 hook `0x8366870`，在主菜单按 A 没有被命中；UI 系统很可能通过 JIT 后的 `CPU.disp` 槽调用，而不是 AOT entry。下一步：

1. 用 `find_cpu.py` 找到游戏线程的 `CPU.disp`，解析 `disp[(0x8366870 - code_lo) >> 2]` 的实际 host 函数；
2. hook 该 host 函数，在主菜单按 A，拿到调用栈和参数；
3. 确认参数（`x0` 控件/上下文，`w1` 玩家或按钮）后，用 `native_input` 桥调用。

### 14.4 disp 槽与首个 hook 结果

`tools/d3-re/trace_ui_disp.py` 直接读运行时 `g_disp` 和 `g_code_lo`，解析 `disp[(pc-code_lo)>>2]` 的 host 函数并 hook。对 `0x8366870`：

- disp 槽里的 host 仍是 `0x7fffd939e9e0`（与 AOT entry 相同），说明该函数没有被 JIT 另行编译；
- 在主菜单按 A 进入游戏时，hook 仍未命中。

所以从开始画面“继续”进入游戏走的不是 `UIConsole_MainMenu_Accept`，至少不是直接经这张表调用；暂停菜单里该项要先把焦点从右侧英雄头像移到左侧列表再按 A。下一步应：

1. 在暂停菜单用左摇杆/鼠标把焦点移到列表，再 hook `0x8366870`；
2. 若仍不命中，hook 表项 6/7/8 和 `UIStartScreen_Console_OnButtonPress`，逐个定位开始画面真正的回调；
3. 找到后确认 `(x0,w1)` 参数，再用 `native_input` 桥调用。

### 14.5 UI 表查找与控件构造

运行时代码里已确认：

- `0x83d14c0` 是表查找函数：hash map 命中后返回 `0x987bf20 + index*0x18 + 0x10` 的 handler；
- `0x83b70c0` 是控件构造函数：按配置 ID 取名字（`0x828f260`），调用 `0x83d14c0`，把回调存到控件 `+0x600`、`+0x690`、`+0x720`、`+0x728` 等槽；
- 这些槽的调用方（真正的事件分发）还没定位。`0x80ea...` 附近的 `blr` 是对脚本全局初始化回调的调用，不是控件事件。

下一步应从控件回调槽的读取处反查：扫描 `ldr xN,[xM,#0x600/0x690]` 后紧接 `blr xN` 且 `xM` 是控件对象（不是全局表）的位置；或在暂停菜单里把焦点移到左侧列表，hook `0x8366870` 验证它是否被调用。

### 14.6 直接调用 UI handler 的探针（未通过）

`native_input` 增加环境变量开关 `SNX_NATIVE_TEST=1`（默认关闭）：游戏显示 3000 帧后，向桥队列提交一次 `UIConsole_MainMenu_Accept(0x8366870, x0=0, x1=0)`，用于确认 handler 的参数需求。

实测两次带该变量的启动都停在“自动存档”提示（约 0.5 秒，尚未到 3000 帧），桥没有执行；不带的干净启动能正常到“按任意键”。因此：

- 探针本身没有被执行，不能据此判断 `x0=0` 是否可用；
- “自动存档”卡住发生在探针入队之前，更像强制结束进程后的存档/系统提示状态，不是桥的调用；
- 探针保持默认关闭，等 UI 事件入口确认后再用真实控件参数调用。

### 14.7 回调槽是对象，不是裸函数指针

`0x83a1db0` 把配置里解析出的回调存到控件 `+0xa8/+0xb0`；析构函数 `0x8064ce0` 对 `+0xb0..+0x48` 逐个取 `[对象]` 的 vtable 并调用 `[vtable+8]`。所以这些槽里是**带 vtable 的回调对象**，事件分发调用的是另一个 vtable 槽。

基础对象 vtable 从全局 `0x9150730` 读取（运行时为 guest `0x90abfe8`），条目包括 `0x8240de0`、`0x8396a30`、`0x8394ce0`、`0x83ac780`、`0x83b7fc0`、`0x83bae20`、`0x8399cb0`、`0x8399d60`、`0x8399a50`、`0x83af7b0` 等。其中 `0x83bae20` 是“是否存在回调”的谓词，不是事件分发；事件方法仍未定位。

暂停菜单的焦点默认在右侧英雄头像，鼠标摇杆左移没有把焦点移到左侧列表（`110-pause-left.png`）。开始画面/主菜单的左键路径仍可用；暂停菜单可先用键盘方向键或 B 关闭。

### 14.8 vtable 方法动态 hook

`tools/d3-re/trace_ui_vtable.py` 读取基础对象 vtable（guest `0x90abfe8`，24 槽），按 `g_disp` 解析每个槽的 host 函数并统计调用次数，然后在按键前后对比。

结果：槽 19/4/7/20/17/16/18 等方法在按键后仍以每秒上万次被调用，属于每帧的更新/绘制/可见性路径，无法从计数上区分“A 按下”的事件方法；`x0..x3` 采样也未成功导出。结论是这套对象系统的每帧调用量太大，不能靠全局 vtable hook 找事件入口。

更可行的下一步：先 hook 控件构造函数（`0x83a1db0` / `0x83b70c0`）拿到某个具体菜单控件对象，再只 hook 这个对象的 vtable/回调槽，按键前后对比。

### 14.9 控件构造 hook 的负结果

`tools/d3-re/trace_ui_widgets.py` 在“按任意键”画面 hook `0x83a1db0`（存 `+0xa8/+0xb0` 回调）后按键加载主菜单：捕获到 0 个控件。另查 `0x83b70c0`（存 `+0x600` 回调）的 disp 槽为 **0**，即它不是 AOT entry、不能用 disp hook；直接 attach 空指针会抛 `access violation accessing 0x0`（已加空指针保护）。

结论：主菜单的控件不是经这两个构造函数在可 hook 的时机创建的，或者创建发生在更早的启动阶段。下一步应：

1. 在启动更早（`dispatch_init` 后、UI 加载前）就 hook 构造函数；
2. 或 hook UI 脚本加载器，拿到脚本上下文后再找控件对象；
3. 或直接从 `0x987bf20` 表项 6 的 `handler` 对象（`+0x10`）反查其创建者/调用者。
