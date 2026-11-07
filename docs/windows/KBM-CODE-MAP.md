# Windows KBM 运行时代码地图

更新：2026-11-07。描述当前源码的实际分层与失败方向，供后续修复定位。当前候选构建 `0122`，SHA-256 `32BC5885F48B3CF299BD4604ECB29B54B146264D50191DFE9CC0C11639314FE8`，补丁链 `0001–0118` 重放 PASS；`0081–0084` 的药水、门户、Space 证据保留为历史。

## 构建与补丁

- 真正编译的源码是 `reference/ScarletNX-src/`；`patches/windows/*.patch` 按 `base.json` 顺序叠加。
- `0079-native-kbm-split.patch` 把原先 3400 行的 `native_world.c` 拆成下列模块；`0080` 调 HUD 字号；`0081` 增加药水标签；`0082` 增加 Act1 城镇传送门 picker；`0083` 修复 mouse UI 聚焦；`0103–0108` 处理底栏直接 pad、技能图标和 HUD；`0113–0115` 放宽 UI 注册表读取并记录桶链；`0116` 修复技能页/地图页的旧焦点与空页面判断，`0117` 接入技能选择器/符文网格点击，`0118` 让底栏 cell 从实时图例解析动作。补丁链共 116 个有效阶段（`0001–0118`，排除归档 `0029/0030`），`verify_patch_chain.py` 重放 PASS。
- 构建产物 `out/windows/build/scarletnx.exe`（0083 `DB9BCB81…`），候选副本 `out/windows/kbm/candidates/0083/scarletnx.exe`、来源 `out/windows/kbm/candidates/0083/manifest.json`（`chain_count` 81；manifest 的 `runtime` 仍为 PENDING，实机证据以 `0083-*.json` 为准）；`0082`/`0081`/`0080` 的 `candidates/` 保留为历史；安装副本在 `D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe`。
- 启动挂起未解决：`0074`、`0079` 在 vsync1 停在 frame10，`0080` fifo/cap60 冷启动复现；vsync0 也有连续冷启动反例（PID `232328` 在 `t=7.387s` 自动存档后 45 秒内未到 title/menu/HUD，`out/windows/kbm/session/takeover-font-startup/0080-vsync-off-cold.json` 为 `success=false`）。卡住的探针进程已终止，当时 0080 保留；不能称关闭 vsync 已可靠绕过。最终重建 `6823E82A…` 的进程 `275864` 经两次 `Space`（第 1 次退出自动回播电影，250 ms 后第 2 次进主菜单）进入主菜单，再以原生 SDL 点击“继续”进入世界，`place 1999503360`；标题输入“阻塞”已纠正为探针间隔过长只跳过自动回播电影。自动存档附近 frame10 Vulkan 11/9 停滞仍是独立未解决问题。`0081` 冷启动 `0081-cold-start.json` 本次 title 18.459 s、menu 18.877 s、world HUD 25.327 s、`success=true`；`0082-cold-start.json` 26.335 s、`0083-cold-start.json` 26.299 s 到 world HUD、`success=true`。其他反例保留，不能泛化启动已修。
- 探针的 RVA 不再硬编码：`tools/d3-re/version.py` 从已安装 exe 的符号表动态解析（`llvm-nm`）；换构建时显式更新 `BUILD.exe_sha256`（必要时同步 `code_dll_sha256`），并由 `assert_installed()` 校验。旧 `sync_probe_version.py --exe` 的手工重绑记录只作历史来源，不再是换构建步骤。`version.py` 已加进程锁：两进程验证拒绝并发且退出释放。

## 模块

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `native_input.c/.h` | host→guest 调用桥、原生动作按键队列 | `native_input_queue`、`native_action_press` |
| `native_guest.c` | guest 内存读写、guest 调用、玩家/实体解析 | `kbm_read*`、`guest_call`、`kbm_local_player` |
| `native_ui.c` | UI 点击分发、页签/服务/物品/地图/底栏处理、关闭与对比状态 | `ui_click`、`ui_map_click`、`ui_close_tick`、`native_ui_take_pointer` |
| `native_labels.c` | HUD 文本 setter 挂钩、底栏图标文案替换 | `world_label`、`ui_footer_relabel`、`native_labels_install` |
| `native_world.c` | 相机射线、寻路目标、攻击/交互、门/传送门、Q/T 命令、hook 安装 | `native_world_click`、`world_tick`、`world_ui`、`world_game`、`native_world_install` |
| `native_kbm.h` | 模块间类型、常量、共享状态和原型 | — |

`native_ui.c` 的特判顺序：物品指针 → 右键 → 底栏图例 → 技能选择器（模式 1/2/3）→ 技能 loadout ring → `ui_map_click` → 页签 → 设置/服务/仓库/选项/卡达拉 → 对话 → 通用焦点控件回调。

## 输入链路

1. `sdl3.c` 从 SDL 事件取值：`Q/T` → `native_world_command`；`1–4` → 鼠标技能队列；`Space` → 角色页/地图时发 B（关闭），其他 UI 走 `native_ui_close_request`；`C/S/J/P` → 面板热键；`Alt` → 对比/技能轮盘；`Esc` → UI 内 B、世界内暂停。
2. 左键 → `native_world_click`：UI 标志进 UI 队列，技能标志进技能队列，否则是世界单指针。
3. `world_game` 每帧消费世界指针/技能队列；`world_ui` 每帧消费 UI 指针与悬停队列。
4. UI 指针 → `pointer_pixel`（按 framebuffer rect 归一化）→ `0x8350BF0` 转 UI 坐标 → `ui_click`。

## 已定位的失败方向

- **HUD 药水标签（0081 已实机复测）**：`world_label` 只处理 `binding < 8` 且逆查 `0x840C650` 结果 `< 6` 的六个技能槽。旧诊断只匹配返回地址 `0x841D050`（技能，玩家在 `x19`），因此看不到药水；按返回地址区分后确认药水 token **确实到达同一个 setter `0x83AD9D0`**，其 LR 为 `0x841D4C4`、玩家在 `x20`。`0081` 仅在 `world_label` 增加该 LR/x20 路由，不扫描注册表；`0081-hud-measured.json`/`0081-hud-retest.json` 测得七槽 18 点、`Q` 14×14。地图底栏和其他底栏仍未覆盖，`Q` 回血效果未在 0081 验证。
- **底栏文案**：世界图例仍替换 `button1..4/l3/l2/r2`。`0085` 在文案含“移动地图”时另外生成 `[拖拽]/[滚轮]/[复位]/[重置]`，但这串只留在宿主缓存；图例对象 `+0x398` 的实时文本仍是摇杆图标。地图摄像机已接到 `localmap+0x214`（缩放 0.5..1.5，正刻度减小）和 `+0x1F8`（平移），由 `native_map_apply` 在游戏线程写入。
- **地图节点**：`ui_map_click` 直接写 `state+0x44/0x48/0x50` 并调 `0x823EF60`，只复刻了“选中/详情”分支，没有把焦点/提交状态交给地图页；`Space` 在地图内被代码固定为 B（关闭），所以“选中后按 Space 传送”在设计上就不会发生。传送应走 A / 底栏“传送”。
- **技能页与地图页焦点（0116 已修）**：C 侧 `ui_object`/`ui_find_key` 的桶遍历本身有效；点击失败的原因是 mouse-opened 页面继承了隐藏的旧焦点，且 `ui_skill_icon` 拿焦点与未赋值的 `state.page=0` 比较。`ui_pointer_page_allowed` 现按 `NormalLayer` 输入订阅和可见模态 owner 守卫页面，`ui_skill_choice` 直接调用原生 `0x823FCE0` 选择、`0x8383CC0/0x83841C0/0x8384280` 应用技能/符文，`ui_skill_icon` 在模式 0 只负责进入选择器。
- **世界页五幕（0081 已实机验证）**：`ui_map_click` 写 `state+0x44` 后调 `0x823EB50` 实际有效；`0081-worldmap-act-matrix.json` 五幕逐幕点击全部 `passed=true`，Act1 哭泣山谷 `2000027656`、Act5 威斯特玛城中区 `1999896582` 已有 place。此前“必须与区域节点 `0x800F9F0 + 0x823EF60` 统一提交链”的推论错误，不再作为前置条件。
- **Space 关闭 UI（0083 已修复 focus 误判）**：`0083` 改用唯一可见输入订阅 prompt 确定 owner，服务/对话允许无键盘 focus 但保留 subscribers 守卫。实机 `0083-prompt-before` 683→`0083-prompt-after` 665 取消退出确认并保留暂停，`0083-prompt-retest` 再通过；`0083-npc-before` 839→`0083-service-after` 734 世界 HUD，`0083-service-retest` 复测通过。`0084` 对没有专用目标的页面改发原生 B：难度 719→665 回到暂停。欧雷克对话两次 Space 关闭回世界。叠加提示仍未验；`0076` 的模态全覆盖不成立。
- **城镇传送门**：`door_candidate_near` 要求同 place、投影命中、遮挡通过、`CAP power > 0`；`0081` 在 Act1 城镇用 `T` 回城到 `2000093193`，SDL 点 SNO `191492` 传送门回到哭泣山谷 `2000027656`（`0081-town-portal-result.json`），portal 被原生消耗、`CAP=30021`。`0082-native-town-portal-picker.patch` 在 `0082` 上已严格串行复测（历史）：`0082-crying-scene`→`0082-town-portal-before`（2000093193、SNO 191492）→`0082-town-portal-result`（2000027656），`0082-town-portal-serial-retest.json` HUD 哭泣山谷；自然场景 `CAP=30021`，不能写 CAP0 已实测；旧 `0082-town-portal-retest` 重叠只读探针不作严格串行验收。`CAP=0`/遮挡与纯鼠标两端仍未完成；Act5 `T` 返回 1 但 place 不变。

## 验证

```powershell
python tools/windows-dev/verify_patch_chain.py        # 116 阶段重放
python tools/windows-dev/test_native_map_picker.py    # 32 项
python tools/windows-dev/test_native_hud_key_labels.py # 56 项
```

历史证据重放测试已移到 `tools/windows-dev/legacy/`，不再默认运行；完成标准只认当前构建的实机业务结果（place/HP/物品/UI 文本前后）。实机驱动脚本 `tools/d3-re/session_driver.py` 一次 attach 可串行发键/点击并回读 UI 与运行时状态。
