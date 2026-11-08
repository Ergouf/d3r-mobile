# D3 Windows 原生键鼠探针

用于 Diablo III `01001B300B9BE000` 在 ScarletNX Windows 运行时上的世界交互、UI 命中与输入证据。当前交接见 [HANDOFF-20261104-CURRENT.md](../../docs/windows/HANDOFF-20261104-CURRENT.md)，操作说明见 [KBM-INPUT-GUIDE.md](../../docs/windows/KBM-INPUT-GUIDE.md)。

所有探针必须**串行**运行。并发 Frida attach 曾导致游戏退出；线程、对象和 PID 都不能跨重启复用。

## 先取身份

```powershell
Get-CimInstance Win32_Process |
  Where-Object Name -eq '01001B300B9BE000.exe' |
  Select-Object ProcessId,ExecutablePath,CreationDate,CommandLine
python tools/d3-re/probe_runtime_state.py --pid <PID>
```

`probe_runtime_state.py` 返回运行时 enabled、`ui_blocked`、点击 serial 和当前世界 goal。探针的 `version.py` 从当前安装 exe 符号表动态解析 RVA，并显式校验 `BUILD.exe_sha256` 与 `code_dll_sha256`；安装构建变化时必须先更新这两个哈希。

## 常用入口

| 目的 | 工具 |
| --- | --- |
| SDL 键盘注入（含 `shift`/`j`/`t` 与 `--mod ctrl`） | `probe_sdl_key.py` |
| SDL 鼠标左键注入 | `probe_pointer_click.py` |
| SDL 按住/拖动鼠标（左/右/中键） | `probe_pointer_hold.py` |
| SDL 移动键短脉冲（贴墙走位） | `probe_walk_hold.py` |
| 世界实体与 native collide/operate | `probe_click_interact.py` |
| 同进程点击 before/after、命令和输入中立性 | `verify_script_interaction.py` |
| 世界点导航与碰撞预检（直行受阻后扇形绕行） | `walk_to.py` |
| 命名 UI 控件快照 | `probe_ui_snapshot.py` |
| 可见 UI 控件树 | `probe_ui_tree.py` |
| 原生 UI hit-test | `probe_ui_pointer.py` |
| 单控件字段/vtable | `probe_ui_object.py` |
| UI navigation group | `probe_nav_group.py` |
| 当前角色页签状态 | `probe_ui_tab_state.py` |
| 世界地图 picker 状态与投影行（只读） | `probe_map_picker_state.py` |
| F2 键位设置/恢复默认（走 F2 后端） | `probe_keyboard_bind.py` |
| F2 当前键位（只读 getter） | `probe_keyboard_bindings.py` |

## 世界点击

```powershell
python tools/d3-re/probe_world_interact.py --pid <PID> --context <CTX> --radius 160 --out out/windows/kbm/session/world.json
python tools/d3-re/verify_script_interaction.py --pid <PID> --target 0x<HANDLE> --seconds 10 --out out/windows/kbm/session/click.json
python tools/d3-re/walk_to.py --pid <PID> --context <CTX> --to 2915,2846 --reach 5 --out-dir out/windows/kbm/session/route
```

要点：

- 世界坐标是游戏单位；SDL 指针与 UI 坐标是 1280×720 引擎像素。
- 改变相机会改变实体投影。日志、截图和点击必须来自同一时刻。
- 碰撞柱命中会变成 entity/attack goal；`walk_to.py` 报 `stopped` 时不能算到达。
- 远处门/portal 的“命令 accepted”不等于 place 改变。

## UI 点击

```powershell
python tools/d3-re/probe_ui_snapshot.py --pid <PID> --match 'consolepause_main|conversation|vendorpanel' --out out/windows/kbm/session/ui.json
python tools/d3-re/probe_ui_tree.py --pid <PID> --visible --out out/windows/kbm/session/tree.json
python tools/d3-re/probe_ui_pointer.py --pid <PID> --screen 541,51 --out out/windows/kbm/session/hit.json
```

当前通用路径支持：

- 有 `+0x118` callback table 的按钮与列表行；
- 已验证的角色页签 controller；
- 商人导航组 2 的购买/出售页签及禁用页签保护；`probe_ui_tab_state.py` 同时记录组编号、玩家和商人控制器模式；
- 14 个装备槽与 11 个技能类别；`0037` 支持图标悬停选择，类别标题和说明随之改变；
- 固定的双按钮确认框形状（尚无焦点/最上层门控）。

当前限制：

- 商人/工匠顶部页签 `0x90ABB48` 的 `+0x118 == 0`；`0035` 商人组 2、`0036` 三类工匠组 5/6/7 由服务表校验后调用原生 selector。启用态修复/回购和工匠交易仍未验收。
- `0x83911f0(button,1,0,0)` 只改变视觉状态，不能用来宣称业务选择。
- `0x816F550(0,slot,0,0)` 只用于已经验证的全局角色页签；错误地用于 vendor tab 会切换到角色页。
- 商人选择器参数为 `0x816F550(2,slot,0,0)`；必须同时核对当前组、四个 callback、控制器模式及活动订阅者，不能只改第一个参数后无条件调用。
- 开关、滑块、滚动列表和重叠控件的完整矩阵尚未完成。
- 卡达拉使用导航组 3；底部“购买”由独立门控调用 `0x81A5E90`，控制器全局 `0x9153278`、vtable `0x90A29E8`、方法 `0x81A3490`。
- 角色页和服务页使用不同控制器。`0038/0039` 通过精确服务 ABI 表选择活动服务，并核对轮盘绑定；完整调用 `0x838F650(selector,key,0x81FC6C0)` 复用原生取消/选中高亮及分类回调。铁匠独立环的分类值不是 0..13，不能套用背包 index。只调用 `0x81FCFD0` 会造成分类已变而光圈/按钮仍停在旧项。

## 探针阅读规则

- `operate accepted`、`submit returned` 和 UI 高亮是中间结果。
- 业务完成至少需要 place 改变、物品数量变化、背包内容变化或明确的 UI before/after。
- 多个 Frida 脚本可在同一 session 内加载；不要从多个 Python 进程同时 attach。
- UI 父链以对象 `+0x38` 的 UIReference 为准；旧的 `+0x20` 解析只用于诊断。
- `probe_ui_named.py` 的 visible 是静态 flags/父链状态，不是完整当前显示状态；使用同轮前后快照判断。
- 所有二进制和截图输出只写 `out/`，不得把唯一存档或密钥放进可清理目录。

## 补丁和版本

轮盘悬停的串行检查（从背包页开始）：

```powershell
python tools/d3-re/probe_wheel_state.py --pid <PID> --out out/windows/kbm/session/wheel.json
python tools/d3-re/probe_pointer_move.py --pid <PID> --engine --x 384 --y 102
python tools/d3-re/verify_hover_wheel.py --pid <PID>
python tools/windows-dev/test_hover_wheel.py
```

`probe_wheel_state.py` 只读当前对象、角色与服务选择器、图标矩形、原生按钮高亮（`+0x464`）、原有光圈的可见性/角度与类别文字；`probe_pointer_move.py` 默认保留 SDL 逻辑像素语义，`--engine` 才按安全区、DPI 和黑边换算。`verify_hover_wheel.py` 同时检查原生高亮、光圈和实际页面内容，所有 attach 严格串行。

已打开服务时可运行 `python tools/d3-re/verify_service_wheel.py --pid <PID> --group <2/5/6/7> --out out/windows/kbm/session/<新的证据目录>`。它逐页检查标准 14 类装备轮盘；没有可见标准轮盘的页只记录 `no-visible-standard-wheel`，不算该页轮盘已验收。铁匠制作的独立武器/护甲轮盘需另行接入，训练页也没有这套轮盘。

工匠键盘训练与本地测试副本的证据检查：

```powershell
python tools/windows-dev/test_artisan_business_evidence.py
python tools/windows-dev/test_service_business_evidence.py
python tools/windows-dev/prepare_artisan_fixture.py --source local/saves/<已核对的备份> --destination local/saves/<新测试副本>
```

副本工具只输出本地文件、不安装或操作游戏；依赖已记录的完整 D3Edit 源码快照和备份清单，拒绝覆盖已有副本。实际游戏加载验证及当前测试存档身份见交接文档。

```powershell
python tools/windows-dev/verify_patch_chain.py
python tools/windows-dev/sync_probe_version.py --exe "D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
```

只按 `patches/windows/base.json` 应用补丁。`0029`、`0030` 已归档，不在当前链中。当前链和业务边界见根仓库的当前交接文档。
