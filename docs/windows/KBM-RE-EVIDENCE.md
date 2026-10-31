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

## 10. 下一步（B1b 剩余 / B2 入口）

1. 找 PC UI 命令分发器：`UI_HUD_ClickPredicate` 表项由谁调用、如何准备 `x19/x20` 和事件参数。
2. 追 `FUN_003dafb0` 的状态机入口，确认 `0x83db4e0` 的调用条件；目标是用 UI 命令注入一次“HUD 点击”。
3. 找世界点击入口：优先看 `PowerCursor*`、`ActionBinding`、HUD 点击后的动作分发；`LeftClickToMove` 目前只是字符串 ID `0x6d7`。
4. 在不写游戏内存的前提下，先做“调用 UI 命令 + 读结果”的探针。
5. 完成 B1b 后提交，再进 B2 的 `input_native=0` 运行时骨架。

## 11. 安全

- 未写存档、未改 `_code.dll`、未改安装目录 exe。
- Frida 探针默认 spawn 后 kill；`--keep` 才会留下进程。
- 所有二进制分析产物在 `out/`（git-ignored）。
