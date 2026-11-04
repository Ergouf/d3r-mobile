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

`probe_runtime_state.py` 返回运行时 enabled、`ui_blocked`、点击 serial 和当前世界 goal。探针的 `version.py` 必须通过 `tools/windows-dev/sync_probe_version.py --exe <安装 exe>` 与当前构建同步。

## 常用入口

| 目的 | 工具 |
| --- | --- |
| SDL 键盘注入 | `probe_sdl_key.py` |
| SDL 鼠标左键注入 | `probe_pointer_click.py` |
| 世界实体与 native collide/operate | `probe_click_interact.py` |
| 同进程点击 before/after、命令和输入中立性 | `verify_script_interaction.py` |
| 世界点导航与碰撞预检 | `walk_to.py` |
| 命名 UI 控件快照 | `probe_ui_snapshot.py` |
| 可见 UI 控件树 | `probe_ui_tree.py` |
| 原生 UI hit-test | `probe_ui_pointer.py` |
| 单控件字段/vtable | `probe_ui_object.py` |
| UI navigation group | `probe_nav_group.py` |
| 当前角色页签状态 | `probe_ui_tab_state.py` |

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
- 14 个装备槽与 11 个技能类别；
- 固定的双按钮确认框形状（尚无焦点/最上层门控）。

当前限制：

- 商人/工匠顶部页签 `0x90ABB48` 的 `+0x118 == 0`；通用点击日志为 `no callback owner`。
- `0x83911f0(button,1,0,0)` 只改变视觉状态，不能用来宣称业务选择。
- `0x816F550(0,slot,0,0)` 只用于已经验证的全局角色页签；错误地用于 vendor tab 会切换到角色页。
- 开关、滑块、滚动列表和重叠控件的完整矩阵尚未完成。

## 探针阅读规则

- `operate accepted`、`submit returned` 和 UI 高亮是中间结果。
- 业务完成至少需要 place 改变、物品数量变化、背包内容变化或明确的 UI before/after。
- 多个 Frida 脚本可在同一 session 内加载；不要从多个 Python 进程同时 attach。
- UI 父链以对象 `+0x38` 的 UIReference 为准；旧的 `+0x20` 解析只用于诊断。
- `probe_ui_named.py` 的 visible 是静态 flags/父链状态，不是完整当前显示状态；使用同轮前后快照判断。
- 所有二进制和截图输出只写 `out/`，不得把唯一存档或密钥放进可清理目录。

## 补丁和版本

```powershell
python tools/windows-dev/verify_patch_chain.py
python tools/windows-dev/sync_probe_version.py --exe "D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe"
```

只按 `patches/windows/base.json` 应用补丁。`0029`、`0030` 已归档，不在当前链中。当前链和业务边界见根仓库的当前交接文档。
