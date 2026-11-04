# D3 原生键鼠：当前证据与方法

> 当前交接入口为 [HANDOFF-20261104-CURRENT.md](HANDOFF-20261104-CURRENT.md)，操作说明见 [KBM-INPUT-GUIDE.md](KBM-INPUT-GUIDE.md)。本文件只保留仍可复用的技术证据，不再保存逐轮日志全文；完整输出仍在 `out/windows/kbm/session/`，该目录可重建且不入 Git。

## 输入与运行时

- 游戏：`01001B300B9BE000.exe`；当前安装版 SHA-256 `F4BF82B64BF2AD1A6B5B7DD0528163820CC3BE0A5979BFFE822C405B23535714`。
- code DLL 未修改：`A829DCE8AC2554A44DF087132CF9D266582010280C660D32A958642C8B7BDA51`。
- 当前操作链路：SDL 事件 → 运行时输入/世界桥 → 游戏自身相机、UI 回调或原生客户端命令。
- 世界点击只接受有效地面或实体；UI 点击先走页签、装备/技能图标、双按钮对话框和原生 callback owner，再回退到 UI 树搜索。
- `native_world_click()` 只排队一次点击，不修改 OS 光标或窗口焦点。鼠标左键坐标必须经过安全区、像素密度和窗口黑边换算。

## 当前关键 ABI

| 对象/入口 | 事实 |
| --- | --- |
| 实体表 | bucket count `+0x100`、buckets `+0x120`、shift `+0x168`；entry `+0` handle、`+0x60/+0x64/+0x68` 坐标 |
| 地面/相机 | `0x813E6A0` 地形拾取；`0x826CA70` 世界点投影 |
| 原生 UI 事件 | widget `vtable+0x60` 的 `0x8392410`；容器事件 `0x83BAD40` |
| UI callback owner | `vtable+0xB0 == 0x83B81F0`，实例 `+0x118` 表、`+0x20` callback |
| 列表 | `vtable+0xE0 == 0x838C6C0`，model `+0x258`，row refs `+0x210`，count `+0x218` |
| 页面 selector | `0x816F550(0, slot, 0, 0)`，仅用于确认过的全局角色页签 |
| 工人/商人页签 | vtable `0x90ABB48`、y≈39、宽≈156；当前 `+0x118 == 0`，没有通用 callback |
| 双按钮框 | 当前 `ui_dialog_buttons()` 按 558×127 根 + 132×66 按钮条识别并发送 A/B，尚无最上层/焦点门控 |

## 已验证路径

- 地面点击移动、远近目标辅助、碰撞柱预检和门进入。
- SNO `178293` 旅店门进入；同轮 place 从 `1999503360` 到 `1999634434`。
- 屋内出口在走近后点击成功返回城镇；远距一键出口未通过。
- 莉娅 SNO `4580` 的“崔斯特姆 / 圣教军 / 取消”三个选项分别命中 `0x820EE30`，同轮 before/after UI 已保存。
- 矿工塔苏恩 SNO `178396` 可由鼠标打开商人面板；商品行命中 `0x81FB910`。
- 顶部五个角色页签通过 `0x816F550` 选择；矩阵为 20 PASS、5 SKIP，不能称 25/25。
- 装备槽 14/14、技能类别 11/11 已由专用 controller setter 选中。
- `0033` 门回退加入 ray/terrain 遮挡验证，stub 测试 22/22，另补重叠门覆盖。
- `0034` 地图键：世界内 `Tab` 打开“新崔斯特姆”地图；地图打开时再次 `Tab` 无输入动作；`Esc` 返回；暂停菜单中的 `Tab` 不再移动焦点。

## 不能成立或必须限定的结论

- 工作台 `Blacksmith_Crafting_Backbone`（SNO `101123`）不是铁匠 NPC。
- 商人/工匠四页签没有找到安全的精确 setter。直接调用全局 `0x816F550(0,1,0,0)` 会把当前导航组切到角色技能页，不能用于 vendor tab。
- 按钮视觉状态 `0x83911f0(button,1,0,0)` 不是业务点击；装备图标实验已经证明高亮变化不等于选中。
- 0027 对话框发送全局 A/B，没有证明点击按钮与当前焦点/最上层一致。
- `operate accepted` 只证明命令被接收；必须再用 place、物品数量、UI 可见性或背包内容作业务门。
- 曾并发 attach 多个 Frida 探针并使游戏退出；后续必须严格串行。

## 复现工具

- `probe_runtime_state.py`：运行时 UI blocked、goal 与版本。
- `probe_ui_snapshot.py` / `probe_ui_tree.py`：命名控件与可见控件树。
- `probe_pointer_click.py` / `probe_sdl_key.py`：无前台、无真实键鼠的 SDL 注入。
- `probe_click_interact.py` / `verify_script_interaction.py`：世界目标、命令与同轮证据。
- `walk_to.py`：相机投影、碰撞预检和世界点行走。
- `probe_nav_group.py`：只读查看当前全局 UI navigation group。
- `verify_patch_chain.py`：按 `base.json` 重放全部有效补丁。

`out/windows/kbm/session/` 中当前 Round 96 证据可确认本次改动；更早逐轮输出只作为历史实验，不作为最终产品验收。
