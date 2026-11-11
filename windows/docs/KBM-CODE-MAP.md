# Windows KBM 运行时代码地图

本文以 `0144` 的 KBM 源码分层和当时的验证为主；当前安装为 `0145`，补丁链至 `0146`（仅修正测试），场景 FSR 实验不等于所有键鼠行为已在 `0145` 重验。当前身份见 [状态](STATUS.md)，验收边界见 [当前交接](HANDOFF-20261104-CURRENT.md)。`0144` canonical SHA-256 为 `C83F70E07A1A5FC217124EE761014EC3AE2E70A34FADD40AE7CB16D4E4858520`。`0141` 增加可交互目标优先，`0142` 接入 F2 自定义 Menu/Confirm/Cancel，`0143` 修复死亡提示，`0144` 处理大碰撞体交互卡住。`0144` 上的 22 项实时矩阵已于 2026-11-09 通过；技能 1/3/4 的完整行为与秘境后段仍未闭环。

## 构建与补丁

- 真正编译的源码是 `windows/source/ScarletNX-src/`；`windows/patches/*.patch` 按 `base.json` 顺序叠加。`0141-native-interact-priority.patch` 处理宝箱/NPC 被近处 actor 碰撞柱抢占；`0142-native-overlay-custom-menu.patch` 把配置的 Menu/Confirm/Cancel 映射到 F2 运行时菜单，原始方向键/Enter/Esc 仍保留为 fallback；`0143-native-death-prompt-input.patch` 在英雄死亡时把 Alt/点击/Esc 分别送到原生 X/Y/B。
- `0079-native-kbm-split.patch` 把原先 3400 行的 `native_world.c` 拆成下列模块；`0080` 调 HUD 字号；`0081` 增加药水标签；`0082` 增加 Act1 城镇传送门 picker；`0083` 修复 mouse UI 聚焦；`0103–0108` 处理底栏直接 pad、技能图标和 HUD；`0113–0115` 放宽 UI 注册表读取并记录桶链；`0116` 修复技能页/地图页的旧焦点与空页面判断，`0117` 接入技能选择器/符文网格点击，`0118` 让底栏 cell 从实时图例解析动作；`0126–0128` 完成 UI Shift 分流、堆叠拆分/数量框点击和重绑定 Pause/Back 门控；`0138–0140` 完成新城门配对传送与 22 项键盘配置；`0141` 交互优先；`0142` F2 自定义菜单；`0143` 死亡提示；`0144` 大碰撞体交互的 stuck operate；`0145` 为独立场景/UI FSR 实验。有效顺序以 `base.json` 为准，排除归档 `0029/0030`。
- 历史 `0140` 构建 SHA-256 为 `8A7BDAFFF759BFFAF6766467E73A5D3AD3829882CFE4CD8673A012FD4800EDB0`，候选副本记录在 `out/windows/kbm/candidates/0140/`；不要把它当作当前安装或当前构建产物的身份。安装路径和实际哈希见 [状态](STATUS.md)。`0126/0127` 分流 UI Shift 与数量框，`0128` 修复重绑定 Pause/Back 的 UI 门控，`0138/0139` 完成新城门精确拾取与配对 portal 传送链，`0140` 扩展全键位。
- 历史启动卡点：`0074/0079/0080` 在自动存档附近出现过 frame10 Vulkan 停滞，FIFO、mailbox 与关闭记录线程分别都有反例。`0129` 为 no-activate 后台启动器增加 `SNX_VK_IMMEDIATE=1`、`SNX_VK_RECORD=0`，并拒绝同 exe 的重叠实例；`0139` 串行冷启动 4/4 成功，`0140` 只记录了定向验证与一次到世界的冒烟，尚不能沿用 `0139` 的结果。普通前台 FIFO 仍保留该历史风险。
- 探针的 RVA 不再硬编码：`windows/d3-re/version.py` 从已安装 exe 的符号表动态解析（`llvm-nm`）；换构建时显式更新 `BUILD.exe_sha256`（必要时同步 `code_dll_sha256`），并由 `assert_installed()` 校验。旧 `sync_probe_version.py --exe` 的手工重绑记录只作历史来源，不再是换构建步骤。`version.py` 已加进程锁：两进程验证拒绝并发且退出释放。

## 模块

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `native_input.c/.h` | host→guest 调用桥、原生动作按键队列 | `native_input_queue`、`native_action_press` |
| `native_guest.c` | guest 内存读写、guest 调用、玩家/实体解析 | `kbm_read*`、`guest_call`、`kbm_local_player` |
| `native_ui.c` | UI 点击分发、页签/服务/物品/地图/底栏处理、关闭与对比状态 | `ui_click`、`ui_map_click`、`ui_close_tick`、`native_ui_take_pointer` |
| `native_labels.c` | HUD 文本 setter 挂钩、底栏图标文案替换 | `world_label`、`ui_footer_relabel`、`native_labels_install` |
| `native_world.c` | 相机射线、寻路目标、攻击/交互、门/传送门、Q/T 命令、hook 安装 | `native_world_click`、`world_tick`、`world_ui`、`world_game`、`native_world_install` |
| `native_kbm.h` | 模块间类型、常量、共享状态和原型 | — |

`native_ui.c` 的特判顺序：堆叠数量框 → 物品指针（含 Shift 拆分）→ 右键 → 底栏图例 → 技能选择器（模式 1/2/3）→ 技能 loadout ring → `ui_map_click` → 页签 → 设置/服务/仓库/选项/卡达拉 → 对话 → 通用焦点控件回调。

## 输入链路

1. `sdl3.c` 从 SDL 事件取值后交 `pc_key_event`。`backend_kbm_bind` 的 22 项配置把原 12 个动作、四向移动、四向菜单导航、确认和取消映射到各自原生路径；`Confirm`/`Cancel` 直接下发原生 A/B，UI 关闭仍受当前页面门控约束。F2 运行时菜单先处理固定 F2/Esc，再经 `overlay_menu_key` 应用自定义 Menu/Confirm/Cancel；原始方向键/Enter/Esc/Backspace 作为 fallback。
2. 左键 → `native_world_click`：UI 标志进 UI 队列，技能标志进技能队列，否则是世界单指针。
3. `world_game` 每帧消费世界指针/技能队列；`world_ui` 每帧消费 UI 指针与悬停队列。
4. UI 指针 → `pointer_pixel`（按 framebuffer rect 归一化）→ `0x8350BF0` 转 UI 坐标 → `ui_click`。
5. `backend_kbm_bind` 将 22 项配置持久化到 `keybinds.ini`，并拒绝冲突键和保留键；旧 12 项文件的 `skills=S` 自动迁移为 `skills=K`，以释放 `S` 给 `Move down`，F2 的 `Restore defaults` 恢复 22 项默认值。

## 已定位的失败方向

- **HUD 药水标签（0081 已实机复测）**：`world_label` 只处理 `binding < 8` 且逆查 `0x840C650` 结果 `< 6` 的六个技能槽。旧诊断只匹配返回地址 `0x841D050`（技能，玩家在 `x19`），因此看不到药水；按返回地址区分后确认药水 token **确实到达同一个 setter `0x83AD9D0`**，其 LR 为 `0x841D4C4`、玩家在 `x20`。`0081` 仅在 `world_label` 增加该 LR/x20 路由，不扫描注册表；`0081-hud-measured.json`/`0081-hud-retest.json` 测得七槽 18 点、`Q` 14×14。地图底栏和其他底栏仍未覆盖；`Q` 已在当前 `0129` 实测受伤后回血，0081 自身仅验证标签。
- **底栏文案**：世界图例仍替换 `button1..4/l3/l2/r2`。`0085` 在文案含“移动地图”时另外生成 `[拖拽]/[滚轮]/[复位]/[重置]`，但这串只留在宿主缓存；图例对象 `+0x398` 的实时文本仍是摇杆图标。地图摄像机已接到 `localmap+0x214`（缩放 0.5..1.5，正刻度减小）和 `+0x1F8`（平移），由 `native_map_apply` 在游戏线程写入。
- **地图节点**：`ui_map_click` 直接写 `state+0x44/0x48/0x50` 并调 `0x823EF60`，只复刻了“选中/详情”分支，没有把焦点/提交状态交给地图页；`Space` 在地图内被代码固定为 B（关闭），所以“选中后按 Space 传送”在设计上就不会发生。传送应走 A / 底栏“传送”。
- **技能页与地图页焦点（0116 已修）**：C 侧 `ui_object`/`ui_find_key` 的桶遍历本身有效；点击失败的原因是 mouse-opened 页面继承了隐藏的旧焦点，且 `ui_skill_icon` 拿焦点与未赋值的 `state.page=0` 比较。`ui_pointer_page_allowed` 现按 `NormalLayer` 输入订阅和可见模态 owner 守卫页面，`ui_skill_choice` 直接调用原生 `0x823FCE0` 选择、`0x8383CC0/0x83841C0/0x8384280` 应用技能/符文，`ui_skill_icon` 在模式 0 只负责进入选择器。
- **世界页五幕（0081 与当前 0132 已验证）**：`ui_map_click` 写 `state+0x44` 后调 `0x823EB50`；当前 `0129` 从新崔斯特姆经世界页第五幕进入威斯特玛 `1999765508`，HUD 为“威斯特玛城中区/传送点”，再按 `T` 取得城门侧门户并鼠标返回。详情名称和 `place` 必须联合验收；同一区域在不同存档/会话的实例键可能不同。
- **Space 关闭 UI（0083 已修复 focus 误判）**：`0083` 改用唯一可见输入订阅 prompt 确定 owner，服务/对话允许无键盘 focus 但保留 subscribers 守卫。实机 `0083-prompt-before` 683→`0083-prompt-after` 665 取消退出确认并保留暂停，`0083-prompt-retest` 再通过；`0083-npc-before` 839→`0083-service-after` 734 世界 HUD，`0083-service-retest` 复测通过。`0084` 对没有专用目标的页面改发原生 B：难度 719→665 回到暂停。欧雷克对话两次 Space 关闭回世界。当前 `0133` 已验证暂停、退出确认、F2 菜单三层按顺序只关闭最上层；`0076` 的模态全覆盖仍不成立。
- **城镇传送门与新城门**：`door_candidate_near` 对 SNO `191492` 使用固定原生 Operate `30021`；`0139` 对 `90419` 门体沿用 Operate，成功后串联 8 单位内的 portal `175482`，单击最终 `place 1999503360→1999634434`。从对侧射线中，隐藏 gate 的深度 `96.35` 大于 terrain `94.16`，被 `door skip` 拒绝；可见 portal 正常操作。CAP=0、双向门及地形遮挡已通过，物件遮挡和目标侧额外独立门仍需负例。

## 验证

```powershell
python windows/tools/verify_patch_chain.py                         # 按当前 base.json 重放
python windows/d3-re/probe_keyboard_bindings.py --pid <PID> --out out/windows/kbm/session/<目录>/bindings.json
python windows/tools/drive_f2_keyboard_ui.py --pid <PID> --phase edit --out out/windows/kbm/session/<目录>/f2-edit.json
python windows/d3-re/session_steps.py --pid <PID> --steps '[{"label":"open","action":{"key":"f3"},"sleep_ms":600}]' --out out/windows/kbm/session/<目录>/steps.json
python windows/d3-re/probe_keyboard_bind.py --pid <PID> --set 12=F --out out/windows/kbm/session/<目录>/bind-set.json
python windows/d3-re/probe_keyboard_bind.py --pid <PID> --reset --out out/windows/kbm/session/<目录>/bind-reset.json
Get-ChildItem windows/tools -Filter test_*.py | ForEach-Object {
    python $_.FullName; if ($LASTEXITCODE) { throw "$($_.Name) failed" } }
```
`probe_keyboard_bindings.py` 只读 getter；`probe_keyboard_bind.py` 走与 F2 相同的后端设置或恢复键位。当前顶层共 20 个 `test_*.py`；`0140` 已重跑 20/20，相关 CTest 7/7，补丁链重放和 `git diff --check` 均通过。
历史证据重放测试已移到 `windows/tools/legacy/`，不再默认运行；完成标准只认当前构建的实机业务结果（place/HP/物品/UI 文本前后）。实机驱动脚本 `windows/d3-re/session_driver.py` 一次 attach 可串行发键/点击并回读 UI 与运行时状态。
