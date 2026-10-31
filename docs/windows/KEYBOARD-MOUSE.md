# 键鼠操作方案（Windows / ScarletNX）

状态：设计稿，未改代码。B0 地址基线、Frida 探针和已确认的 PC 输入字符串见 [KBM-RE-EVIDENCE.md](KBM-RE-EVIDENCE.md)。目标是把《暗黑破坏神 III》Switch 版在 ScarletNX 运行时里做成“键鼠可玩”，并给出两条路线：A. 手柄级保底；B. 按 d2r-mobile 的做法接回原生 PC 输入层。本稿针对 Windows 运行时；Android 的 `d3-android` 输入链路不同，只复用思路，接入点需另做。

## 1. 结论

**能做，而且要分两层看：先做“键鼠当手柄”保底，再按 d2r-mobile 的路线做“原生 PC 输入层”。**

- **A. 手柄级（确定能做）**：键盘全键位重映射；鼠标按键映射到 A/B/X/Y/L/R/ZL/ZR；鼠标位置驱动左摇杆；鼠标快速甩动驱动右摇杆（翻滚）；滚轮/侧键做菜单和技能。改动在运行时内，SDL3 已是现有依赖。
- **B. 原生 PC 输入层（d2r-mobile 已证明可行，D3 有明确证据）**：绕过 Switch 的 HID 鼠标后端，直接向游戏的 UI/动作层注入鼠标事件，或调用游戏自己的 PC 点击入口。这样可以得到真正的“点地板走位、点 UI、点目标交互”，而不是用摇杆模拟。
- **不能提前断言“做不到”**：之前说“游戏只消费 Npad”，只对 Switch 的 HID 后端成立。d2r-mobile 证明 Switch 版可以保留 PC 的 UI/鼠标消息处理；D3 的 NSO 里也保留了 `LeftClickToMove`、`RightClickAttack`、`UseCommandClickAsRightClick`、`Mouse1..5`、`SkillLeftMouse/RightMouse` 等 PC 动作名，`ClientCommon.cpk` 里同时有 PC 和 Console 两套 UI。正确做法是先做探针，而不是直接否定。
- **推荐顺序**：先用 A 保证“今天能玩”；同时按 B 做最小探针（世界点击 → UI 点击 → 键盘），探针成功后再决定投入。
- **外部现成方案只适合快速验证**：ViGEmBus + 自写 feeder，或付费的 reWASD。开源库里没有“键鼠 → D3 Npad”的完整现成方案。

## 2. 两条链路：HID 后端 vs PC 输入层

先把“游戏不读鼠标”拆开看。Switch 的输入有两条不同的链路：

1. **HID 后端**：游戏通过 `nn::hid` 读 Npad / 鼠标 / 键盘。D3 的 NSO 只看到 Npad 系列导入（`GetNpadStates`、`InitializeNpad` 等），**没有看到 `hidGetMouseStates` / `hidGetKeyboardStates`**。所以直接往运行时的 HID 鼠标环里填数据大概率不生效；运行时 `hid.c:430` 现在推的就是全零。
2. **PC UI / 动作层**：D3 是 PC 版移植，Switch 包里仍然保留了大量 PC 侧字符串和资源，例如：
   - `LeftClickToMove`、`RightClickAttack`、`UseCommandClickAsRightClick`
   - `Mouse1` .. `Mouse5`、`IsMouseAssignable`、`SkillLeftMouse` / `SkillRightMouse`
   - `UI_HUD_ClickPredicate`、`UI_Key_Binded`、`SCRIPT_REFERENCE_PC_ONLY`
   - `ClientCommon.cpk` 里同时有 `UI\GameMenu.ui`、`UI\ToolTip.ui`、`UI\PlayingHotkeys.ui` 和 `UI\ConsoleMainMenu.ui`、`UI\ConsoleControllerLayout_NX64.ui`、`UI\ConsolePlayingHotkeys.ui`；还有 `TextBtnMouseover*`、`EditBoxCursor.an2`、`DropDownItemMouseover00.an2` 这些 PC 鼠标 UI 资源
   - `CoreCommon.cpk` 里有 `StringList\KeyNames.stl`（键名表），说明 PC 键位/动作数据也在包里

d2r-mobile 做的正是**绕过 HID 后端，直接走第二层**：向 UI 根控件发 `InputMessage`（`MouseMove` / `LeftMouseButtonDown/Up` / `MouseScroll` / `KeyDown/Up`），世界点击则调用游戏自己的点击入口 `main+0x4ace20`（与手柄主按钮、PC 左键共用）。它没有“让 Switch 系统多出一个鼠标设备”，而是把 PC 输入层重新接上。

参考代码的位置：

| d2r-mobile 文件 | 作用 | D3 可借鉴的部分 |
| --- | --- | --- |
| `dm/host/dm_cursor.c` | 把触点/鼠标变成 UI 消息：`MouseMove`、`LeftMouseButtonDown/Up`、`MouseScroll`，发到 UI 根控件的消息处理函数 | UI 事件注入的架构；D3 的消息结构/地址要重找 |
| `dm/host/dm_world.c` | 点世界目标 / 点地板：调用游戏自己的点击入口 `main+0x4ace20`，共用 PC 左键和手柄主按钮 | 世界点击入口的调用方式；D3 要找等价函数 |
| `dm/host/dm_padmode.c` | 改写 UI 布局前缀（`Controller/Console/Switch/` 等），在控制器/触屏 UI 之间切换 | D3 若要强制 PC 布局，可照这个思路改前缀 |
| `dm/host/hle_hid.c` | Npad / 触摸的 HID 共享内存 | 输入状态注入的位置；D3 的 Npad 路径 |
| `dm/ios/tools/touch_layout.py` | 把控制器布局替换成键鼠布局 | D3 的 PC/Console 布局替换参考 |

所以现在的判断应该是：**D3 也有这条第二层的入口，只是还没找到 D3 的地址；不是“游戏逻辑上不可能”。**

外部映射软件仍然有两个实际问题：

- **双重输入**：外部虚拟手柄和运行时写死的 WASD 都会驱动玩家 1 的左摇杆。`video_poll` 里键盘摇杆优先于手柄（`sdl3.c:1012`），所以鼠标转向会被 WASD 覆盖，反之亦然。
- **驱动退役**：ViGEmBus / ViGEmClient 已停止维护（end-of-life），虽然 1.22 仍可用，但它是内核驱动，长期分发不合适。

## 3. 现有公开库/工具的真实方向

| 项目 | 许可 | 实际方向 | 能否直接用在本题 |
| --- | --- | --- | --- |
| SDL3 | zlib | 键鼠/手柄采集、相对鼠标、虚拟摇杆 | **能**，运行时已链接，首选 |
| ViGEmBus | BSD-3-Clause | 只提供虚拟 Xbox/DS4 手柄驱动 | 只解决“虚拟手柄”，映射要自己写；已退役 |
| ViGEmClient | MIT | ViGEm 的 C/C++ feeder SDK | 同上，适合自写外部工具 |
| vgamepad | MIT | Python 的 ViGEm 封装 | 适合 1 小时做原型，不适合长期分发 |
| JoyShockMapper | 开源（自定义许可） | **手柄 → 键鼠**，以及手柄 → 虚拟手柄 | 方向反了，不能把键鼠变成手柄 |
| AntiMicroX | GPL-3.0 | **手柄 → 键鼠**（给不支持手柄的游戏用） | 方向反了，不适用 |
| Steam Input | 闭源 | **手柄 → 键鼠/虚拟手柄** | 方向反了，不适用 |
| reWASD | 闭源付费 | **键鼠 → 虚拟手柄**，支持鼠标当摇杆 | 唯一开箱可用的现成方案，但要付费 |
| vJoy + AutoHotkey | 开源组合 | 键鼠 → 虚拟手柄 | 可行但驱动老、签名/兼容性差，不建议作为发行方案 |
| SDL3 虚拟摇杆 | zlib | 进程内虚拟手柄 | 只能被本进程看到，不能给另一个进程注入 |
| d2r-mobile | MIT | Switch 版 D2R 的完整移植：UI 鼠标消息注入、世界点击入口、PC 布局切换 | **参考实现**，不能直接复用 D3 的地址，但可复用架构和探针方法 |

结论：**开源生态没有“键鼠 → D3”的现成库；但 d2r-mobile 的代码证明这条路存在，而且它的 `dm_cursor.c` / `dm_world.c` / `dm_padmode.c` 就是可照着做的参考实现。** 剩下的是 D3 自己的地址和 UI 结构，不是从零发明。

## 4. 目标操作方案

### 4.1 键位

以 Switch Npad 的按钮名为准（A 在右、B 在下），不受 `gamepad_swap_ab` 影响；物理手柄仍按原设置。

| 输入 | 游戏动作 | Npad |
| --- | --- | --- |
| W A S D | 移动 | 左摇杆 |
| 鼠标位置（steer 模式） | 朝指针方向移动 | 左摇杆 |
| 鼠标左键 | 主技能/确认 | A |
| 鼠标右键 | 次技能/取消 | B |
| 鼠标中键 | 技能 3 | X |
| 鼠标侧键 4 | 技能 4 | Y |
| 鼠标侧键 5 | 药水/辅助 | L 或 ZL（可配） |
| 1 / 2 / 3 / 4 | 四个技能槽 | A / B / X / Y |
| 空格 | 翻滚 | 右摇杆瞬间推满 |
| 鼠标快速甩动 | 翻滚（可选） | 右摇杆瞬间推满 |
| Q / E | L / R | L / R |
| Tab / M / H | 背包、地图、游戏菜单 | Minus |
| Enter | 另一菜单 | Plus |
| 方向键 | 快捷栏/菜单 | 十字键 |
| 滚轮上/下 | 快捷栏或菜单上下 | 十字键上/下（可选） |
| F1/F2/F3/F4/F5/F11/Esc | 运行时功能 | 不进入游戏 |

说明：

- D3 主机版自动锁定最近目标，所以**不需要鼠标瞄准**；鼠标主要承担移动和翻滚。
- 四个技能在游戏内“选项 → 操作”里可以改，键位表只是默认值。
- `Esc` 保持运行时退出，不能映射成游戏菜单；用 `H`（Minus）代替。

### 4.2 鼠标三种模式

在 `.ini` 里用 `mouse_mode` 选择：

1. **`steer`（推荐，默认）**
   - 以游戏画面中心为原点，光标方向 → 左摇杆方向；离中心越远，推杆越大。
   - 中心死区 `mouse_deadzone`，最大推满半径 `mouse_radius`（都按画面短边百分比）。
   - 光标可见；不需要相对鼠标模式。
   - 这是“朝指针方向走”，不是“点地板自动寻路”。遇到障碍要自己转方向。

2. **`stick`**
   - 相对鼠标模式：鼠标移动量累积成左摇杆，停止移动后约 150–250 ms 回中。
   - 光标隐藏，适合像摇杆一样推着走。
   - 需要 `SDL_SetWindowRelativeMouseMode(win, 1)`；打开运行时菜单（F2）时自动退出相对模式，否则菜单指针不能用。

3. **`flick`**
   - 只把快速甩动变成右摇杆脉冲，用于翻滚；不驱动移动。
   - 50 ms 窗口内速度超过 `mouse_flick_threshold`，推满右摇杆 `mouse_flick_ms`（约 90 ms），冷却 250 ms。
   - 也可以不用鼠标甩动，直接按空格：沿当前移动方向推右摇杆 90 ms。

4. **`off`**
   - 鼠标只保留菜单指针和 `touch=2` 的原有行为。

**输入优先级**：按“最后活动的设备”仲裁，而不是硬编码。鼠标刚动过就用鼠标摇杆；键盘/手柄摇杆一动就交还给键盘/手柄。按钮始终按位或，不冲突。

### 4.3 原生层要验证的（不再预先判死）

| 目标 | d2r-mobile 的做法 | D3 的现状 / 探针 |
| --- | --- | --- |
| 鼠标点地板，角色寻路过去 | 调用游戏自己的点击入口 `main+0x4ace20`（与 PC 左键、手柄主按钮共用） | NSO 保留 `LeftClickToMove`、`UseCommandClickAsRightClick`；先找 D3 的等价点击入口 |
| 鼠标点游戏内 UI | 向 UI 根控件发 `InputMessage` 的 `MouseMove` / `LeftMouseButtonDown/Up` | `.ui` 里有 `OnClick` / `Mouseover` / `OnHotKey`；找 D3 的 UI 消息分发 |
| 键盘热键 / 文本 | 发 `KeyDown` / `KeyUp`，或调用游戏动作 | NSO 保留 `UI_Key_Binded`、`Mouse1..5`、`ActionBinding`；找按键动作分发 |
| 指针瞄准 | D2R 有鼠标瞄准；D3 主机版自动锁定 | **不需要**；D3 的鼠标主要用于走位和 UI |
| 鼠标转镜头 | D2R 不需要 | D3 镜头固定等距，右摇杆只用于翻滚；**不需要** |

真正的限制是 **D3 的地址/UI 结构/版本适配和工作量**，不是“游戏没有这条逻辑”。如果探针失败，再退回 A 方案，而不是一开始就否定 B。

### 4.4 原生模式键位

如果 B 探针成功，键位直接回到 D3 PC 默认，不再经过 Npad 映射：

| 输入 | 动作 |
| --- | --- |
| 鼠标左键 | 点地板走位 / 点目标攻击或交互 / 点 UI |
| 鼠标右键 | 次要技能 / 强制移动（以游戏内绑定为准） |
| 鼠标滚轮 | 缩放或列表滚动（以游戏内绑定为准） |
| 1 / 2 / 3 / 4 | 技能槽 |
| Q / E | 药水 / 辅助（以游戏内绑定为准） |
| Tab / I / M / Esc | 地图 / 背包 / 菜单（以游戏内绑定为准） |
| W A S D | 可选：保留为摇杆移动，作为鼠标走位的替代 |

下面的 Npad 表只在 A 方案（手柄级保底）使用。

## 5. 实现落点

### 5.1 文件与改动

| 文件 | 改动 |
| --- | --- |
| `src/nx/runtime/settings.txt` | 新增 `g_input_ini`（放在 `[Controllers]` 段）：`input_mouse`、`mouse_mode`、`mouse_sensitivity`、`mouse_deadzone`、`mouse_radius`、`mouse_flick`、`mouse_flick_threshold`、`mouse_flick_ms`、`keyboard_map`、`mouse_map`、`mouse_steer_button`。改完由 `settingsgen` 重新生成 `snx_settings.h`，不要手改生成物 |
| `src/nx/runtime/platform/backend/sdl3.c` | 新增输入状态与事件处理；替换 `keymap()`；在 `video_poll` 合并；菜单/失焦/相对鼠标处理；HELP 文本 |
| `src/nx/runtime/platform/backend.h` | 声明新的 `input_*` 接口（如果拆成独立模块） |
| `src/nx/runtime/platform/overlay.c` | 可选第二阶段：新增“Keyboard & mouse”页，或在现有 Controllers 页加行 |
| `src/nx/runtime/platform/backend/gamepad.c` | 不改；物理手柄继续走原路径 |

新增一个 `platform/input_map.c/.h` 也可以，但第一版直接放 `sdl3.c` 更省事；等逻辑稳定再拆。

### 5.2 数据结构

```c
typedef struct {
    u64 buttons;      /* Npad 按钮位，和 keys_held 同一套 */
    i32 lx, ly;       /* 左摇杆 -32767..32767 */
    i32 rx, ry;       /* 右摇杆 */
    u64 last_ms;      /* 最后活动时间，用于仲裁 */
} SnxInputState;
```

键盘仍复用现有的 `keys_held` 位图；鼠标按键单独一个 `mouse_buttons`。不要重写 `pad1` 写入逻辑，只在现有合并点插一层。

### 5.3 事件处理

在 `video_poll` 的 `switch (e.type)` 里加：

```c
case SDL_EVENT_MOUSE_BUTTON_DOWN:
case SDL_EVENT_MOUSE_BUTTON_UP:
    input_mouse_button(&e);   /* 映射到 mouse_buttons；touch_mouse 仍在前面处理 */
    break;
case SDL_EVENT_MOUSE_MOTION:
    input_mouse_motion(&e);   /* steer 用绝对位置；stick/flick 用 xrel/yrel */
    break;
```

注意顺序：`overlay_event(&e)` 必须继续在最前面。菜单打开时鼠标事件被菜单消费，不能再进游戏。

键盘：

```c
case SDL_EVENT_KEY_DOWN:
    if (!e.key.repeat) keys_held |= input_keymap(e.key.scancode);
    break;
case SDL_EVENT_KEY_UP:
    keys_held &= ~input_keymap(e.key.scancode);
    break;
```

`input_keymap()` 用 `keyboard_map` 查表；默认值与现在的 `keymap()` 完全一致，保证不配置时行为不变。

### 5.4 合并点

现有代码在 `sdl3.c:968` 之后：

```c
u64 s = unattended_buttons(), k = keys_held | s;
u64 nonpad = (k & 0xFFFFull) | (s & 0xFF0000ull), b;
i32 st[4], pad[4], pad0[4];
input_key_sticks(k, st);
i32 lx = st[0], ly = st[1], rx = st[2], ry = st[3];
```

建议改成：

```c
u64 k = keys_held | unattended_buttons();
SnxInputState in = {0};
input_keyboard_state(k, &in);
input_mouse_state(&in);          /* 含 steer / stick / flick / 按钮 */
u64 nonpad = (in.buttons & 0xFFFF) | ...;
i32 lx = in.lx, ly = in.ly, rx = in.rx, ry = in.ry;
```

然后保留后面的 vpad 覆盖、`input_stick_clamp`、菜单置零、写 `g_hle.hid.pad1`。这样物理手柄的 `pad0` 回退逻辑（`sdl3.c:1012`）仍然有效。

### 5.5 菜单、失焦、触摸

- `menu_open(1)`：退出相对鼠标模式，清空鼠标摇杆和鼠标按键，显示光标；`menu_open(0)` 时如果 `mouse_mode=stick` 再进入相对模式。
- `SDL_EVENT_WINDOW_FOCUS_LOST`：清空 `mouse_buttons`、鼠标摇杆、flick 累积；`SDL_SetWindowRelativeMouseMode(win, 0)`。
- `touch=2` 与鼠标左键冲突：`input_mouse=1` 时默认把 `touch` 当 0 处理，或加 `mouse_touch=1` 显式允许“左键既是 A 又是手指”。不要默认两个都开。
- 游戏自己的菜单（Minus）运行时不知道；`steer` 在游戏菜单里可能仍推左摇杆，需要实测。若游戏菜单会响应摇杆，按 H（Minus）时短暂禁用摇杆 500 ms，或把 `mouse_mode` 切到 `off`。

### 5.6 配置示例

```ini
[Controllers]
input_mouse=1
mouse_mode=steer
mouse_sensitivity=1.0
mouse_deadzone=6
mouse_radius=35
mouse_flick=1
mouse_flick_threshold=1200
mouse_flick_ms=90
mouse_steer_button=
keyboard_map=1:A 2:B 3:X 4:Y q:L e:R tab:Minus m:Minus h:Minus space:Dodge
mouse_map=left:A right:B middle:X back:Y forward:L
```

上面的 `keyboard_map` 是示意格式，实际解析器可以复用 `pad_map.h` 的“控制:按钮”风格，也可以自己写 `key:action`。关键是默认值必须等于当前 `keymap()`，升级后不配置也能玩。

### 5.7 B 方案探针：把 D3 的 PC 输入层接回来

B 方案不是“再写一个映射器”，而是像 d2r-mobile 一样，在运行时里调用游戏自己的 PC UI/动作函数。顺序如下，每一步都能独立判断成败：

1. **准备可调用的游戏代码**
   - `01001B300B9BE000_code.dll` 只导出 `snx_module`，内部函数按“模块基址 + guest 偏移”调用；这和 d2r-mobile 的 `main+0x...` 是同一类做法。
   - 原始 NSO 在 `local/assets/exefs_update/main.nso0`，可用 `hactool --uncompressed` 解出；项目已有 `d3-android/tools/dis_guest.py`、`find_calls.py`、`resolve_guest.py` 可做反汇编和交叉引用。
   - 注意：D3 的 `LeftClickToMove` 等名字在 SNO 字符串表里，代码引用的是哈希/索引，不是直接的 `ADRP+ADD` 字符串指针；直接搜 xref 找不到。B0 要先定位 action id / 哈希和动作分发表，再谈调用。
   - 先校验 build id，只对当前版本做偏移；换版本必须重找。

2. **世界点击探针（最高价值）**
   - D3 的 NSO 保留 `LeftClickToMove`、`RightClickAttack`、`UseCommandClickAsRightClick`。先在 rodata 里定位这些字符串，再找引用它们的动作分发函数。
   - 目标：在城镇里用鼠标点一块空地，角色走过去的**同一条路径**被触发。d2r-mobile 的等价物是 `dm_world.c` 里的 `main+0x4ace20(player, 7, x, y, 0)`；D3 需要找自己的点击入口，不要自己写寻路。
   - 如果只找到“屏幕点 → 世界点”的投影函数，也可以先调用投影，再交给点击入口；不要绕过游戏自己的点击逻辑。

3. **UI 点击探针**
   - D3 的 `.ui` 里有 `OnClick` / `Mouseover` / `OnHotKey`；先在 UI 根控件/消息分发处找 `OnClick` 的分发点。
   - d2r-mobile 的等价物是 `dm_cursor.c` 里的 `ui_send_mouse()`：消息 `{category hash, action hash, payload}` 发到 UI 根控件，payload +4/+8 是光标坐标，+0x10 是滚轮/按键。
   - 如果 D3 的 UI 消息结构不同，先做一个“只移动光标、不点击”的探针：在主菜单里把光标移到“选项”上，看 hover 是否出现；再发点击。
   - 退路：不接原生 UI 消息，先用鼠标驱动**主机版光标**（右摇杆/绝对坐标）+ A 键点击。这仍然是“键鼠能点 UI”，只是没有 hover 的鼠标语义。

4. **键盘探针**
   - D3 的 NSO 保留 `UI_Key_Binded`、`Mouse1..5`、`KeyBindingVersion`、`ActionBinding`。先找按键动作分发，再发 `KeyDown` / `KeyUp`，或直接调用动作。
   - 不要只把键盘映射成 Npad；B 方案的目标是让游戏的 PC 键位（Tab 地图、I 背包、1-4 技能）走原来的动作层。

5. **PC 布局探针（可选）**
   - `ClientCommon.cpk` 里同时有 PC 的 `UI\GameMenu.ui`、`UI\ToolTip.ui` 和 Console 的 `UI\ConsoleMainMenu.ui`。如果 Console 布局对鼠标不友好，再考虑像 `dm_padmode.c` 那样改写布局前缀、强制加载 PC 布局。
   - 这一步不是前置条件；世界点击和键盘动作可以先在 Console 布局下工作。

**验收标准**：城镇点地面能走；点 NPC 能走过去并交互；点 UI 按钮能触发；按 Tab/I/1-4 能触发对应动作；Alt+Tab 后没有卡住的鼠标键；连续 30 分钟不漂移。全部通过才算 B 方案成立；只通过 UI 点击则算“半原生”，游戏内仍用 A 方案走位。

## 6. 分阶段实施

| 阶段 | 内容 | 预计 |
| --- | --- | --- |
| A0 | 备份 `01001B300B9BE000.exe`，确认 F1/F2、Alt+Enter、手柄正常 | 10 分钟 |
| A1 | 键盘可配：`keymap()` → 查表；默认表不变；`.ini` 可改 | 0.5 天 |
| A2 | 鼠标按键 → Npad；`touch=2` 冲突处理；失焦清理 | 0.5 天 |
| A3 | `steer` 左摇杆 + 死区/半径/优先级 | 1 天 |
| A4 | `stick` 相对鼠标 + F2 菜单切换；`flick` 翻滚 | 1 天 |
| A5 | 可选：运行时菜单加键鼠设置页；Android 输入层复用 | 1–2 天 |
| A6 | 手测与调参（灵敏度、回中、翻滚阈值） | 1 天 |
| B0 | 解 NSO、定位 `LeftClickToMove` / UI `OnClick` 的引用 | 1–2 天 |
| B1 | 世界点击入口：城镇点地面能走 | 2–5 天 |
| B2 | UI 光标 / 点击：主菜单按钮能点 | 2–5 天 |
| B3 | 键盘动作分发：Tab/I/1-4 走原动作层 | 2–4 天 |
| B4 | PC 布局（可选）、失焦/菜单保护、稳定性 | 3–7 天 |

A1/A2 可以当天做完并验证；B0 可以并行开始。**先做 B0/B1，不要等 A 全做完**：世界点击是判断“原生键鼠”是否成立的关键，越早探越好。

## 7. 验证清单

**A 方案（手柄级）**
- F1 帮助、F2 菜单：鼠标指针仍可用；菜单打开时角色不动。
- 城镇走、战斗、翻滚、四个技能、背包、地图、游戏菜单各一遍。
- Alt+Tab / 失焦 / 恢复：没有卡键、没有卡摇杆、没有光标消失。
- Alt+Enter 全屏 / 窗口切换：`steer` 的中心按画面矩形算，不是按窗口，黑边时不偏。
- 物理手柄同时连接：手柄一动就接管摇杆，鼠标一动就交还；按钮不冲突。
- `touch=2` 关闭后，鼠标左键不再触发触摸；打开时行为符合预期。
- 连续玩 30 分钟：无漂移、无累积、无越推越偏。

**B 方案（原生 PC 输入层）**
- 城镇点空地：角色沿游戏自己的寻路走过去，不是直线撞墙。
- 点 NPC / 怪物 / 物品 / 出口：走过去并交互，和 PC 版左键一致。
- 点 UI 按钮：主菜单、背包、技能页各点一个，hover 和点击都有反应。
- 键盘：Tab 地图、I 背包、1-4 技能、Esc 菜单各触发一次；文本输入框能输入。
- 打开游戏菜单 / 运行时 F2 / 失焦：鼠标不穿透、不卡键、不误点。
- 连续玩 30 分钟：无漂移、无重复点击、无鼠标位置累积误差。

## 8. 风险

- **ViGEm 已退役**：外部方案依赖一个不再维护的内核驱动；虽然 1.22 仍可用，但长期分发和支持不合适。运行时内方案没有这个问题。
- **相对鼠标与菜单冲突**：F2 菜单必须临时退出相对模式，否则鼠标指针不能点。这是实现时最容易漏的。
- **游戏菜单未知**：运行时不知道游戏自己的菜单何时打开；`steer` 可能在菜单里推摇杆，需要实测后加保护。
- **没有自动化测试**：输入手感只能手测；建议把灵敏度/死区做成可热调，减少反复构建。
- **B 方案可能只成功一半**：世界点击、UI 点击、键盘动作是三个独立入口，可能只接上 UI 或键盘。先按探针结果决定交付范围，不要再用“不是 PC 版”提前否定。
- **B 方案绑定版本**：地址、UI 结构、字符串偏移都按当前 build id；游戏更新后要重找。做之前先记录 build id，并保留原始 NSO。
- **反汇编工作量**：d2r-mobile 的 `dm_cursor.c` / `dm_world.c` 是长期逆向的产物；D3 不是照抄地址就能用，必须按 D3 的 UI/动作结构重做探针。

## 9. 建议

1. **先做 B0/B1（世界点击探针）**：这是“原生键鼠”是否成立的唯一硬指标。城镇点地面能走，就继续 B2/B3；不能走，再决定是否只交付 A 方案。
2. **同时做 A1/A2 保底**：键盘可配、鼠标按键当天能出；即使 B 只成功一半，也有可用的键鼠方案。
3. **B1 成功后再做 B2/B3**：UI 点击、键盘动作分别验收；不要一次全做，失败时无法定位是 UI 还是动作层。
4. 外部方案只用来做 A/B 对比：`vgamepad` + 一个 Python feeder 一小时能验证“虚拟手柄能不能被 ScarletNX 认出”，但不要把它当发行方案。
5. 只有 B 方案确认失败、且你只接受 PC 版手感时，才走 PC 版；不要因为 A 方案不完美就否定 B。

### 快速验证（不改运行时）

想先确认“虚拟手柄 + 鼠标转向”这条路通不通，可以做一个最小外部验证：

1. 安装 ViGEmBus 1.22，`pip install vgamepad pynput`。
2. Python 里建一个 Xbox 360 虚拟手柄；把鼠标位置相对游戏窗口中心的向量写进左摇杆，左键/右键写 A/B。
3. **不要映射 WASD**：运行时的 `keymap()` 会同时驱动左摇杆，造成双重输入。`.ini` 里把 `touch=0`，避免左键又当触摸。
4. 如果角色能朝鼠标方向走、能放技能，说明链路成立；手感是否可接受再决定要不要做运行时内版本。

这个验证的缺点：没有键盘移动、没有翻滚、鼠标转向是“绝对位置”，而且多一个内核驱动。它只适合判断可行性，不适合日常使用。
