# 仓库协作约定

当前 Windows KBM 交接入口：[`docs/windows/HANDOFF-20261104-CURRENT.md`](docs/windows/HANDOFF-20261104-CURRENT.md)。操作说明见 [`docs/windows/KBM-INPUT-GUIDE.md`](docs/windows/KBM-INPUT-GUIDE.md)，技术证据见 [`docs/windows/KBM-RE-EVIDENCE.md`](docs/windows/KBM-RE-EVIDENCE.md)。

## 开始任务

1. 先确认 Serena MCP 可连接；已有服务复用，不重复启动。入口为 `http://127.0.0.1:9144/mcp`，客户端为 `d3-android/tools/serena_query.py`。
2. 服务不可用时使用隐藏窗口启动，日志写入 `out/`：`serena start-mcp-server --project "D:/workspace/Diablo(fegnjl)" --transport streamable-http --host 127.0.0.1 --port 9144 --enable-web-dashboard false --enable-gui-log-window false --open-web-dashboard false`。
3. 每会话调用一次 `initial_instructions`，再用 `get_current_config` 或符号查询确认项目已激活。
4. 分析 `reference/ScarletNX-src` 时单独激活该 Serena 项目。主仓库忽略该目录，不能把主项目空结果当成源码不存在。
5. Serena 失败先定位并修复；仍不可用时说明原因，按最小范围用其他方法继续，不能伪称已使用。

## 代码探索与验证

- 优先使用 Serena 的符号概要、符号查询和引用查询；只有符号级上下文不足时才读取完整文件。
- 每轮结束使用不继承对话上下文的独立子代理 review（`fork_turns=none`）。发现问题后修复并复查；未验证项不能写成完成。
- 不并发运行 Frida 探针。并发 attach 曾导致游戏退出；所有探针必须一次一个。
- 业务完成必须有可观察结果（place、背包/物品、UI before/after、资源数量等）。`operate accepted`、`submit returned`、编译成功或 UI 高亮都不够。
- 进程身份必须同时核对完整 exe 路径、启动时间和 SHA-256；PID 会被复用。

## 电脑界面操作

最新用户可以随时改变交互授权。执行时先查看本条和用户当前消息：2026-11-04 本轮要求只用脚本探针，不使用 computer-use、第二屏幕或置顶。

默认的 computer-use 约束仍为：如需电脑界面或视觉交互，委派给 `gpt-6.1-terra` 子代理；主代理不自行执行。模型不可用时说明，不擅自改用其他模型。该默认不等于当前脚本探针轮次的许可。

## 游戏窗口

- 新启动统一使用 `tools/windows-dev/Launch-Background.ps1`：1024×576、(40,40)、后台、非置顶、`SWP_NOACTIVATE`。
- 不调用 `SetForegroundWindow` / `SetActiveWindow`，不设置 topmost，不把窗口拉回前台。
- 不用真实光标或 `SendInput` 绕过后台窗口限制。
- 当前脚本注入链路使用 SDL 事件、游戏线程调用和只读内存探针；探针与构建产物写入 `out/`。

## KBM 范围

- 目标是原生键盘/鼠标事件、世界点击、目标交互、游戏 UI 和菜单，不接受键盘转 Npad、鼠标转摇杆或“改焦点再发 A”作为交付替代。
- 已实现并不等于业务完成；以 [当前交接](docs/windows/HANDOFF-20261104-CURRENT.md) 的状态表为准。
- `0029`、`0030` 已归档；补丁永远只按 `patches/windows/base.json` 的链应用。
- 仓库路径含括号，构建使用无括号 junction：`D:\workspace\Diablo-kbm`。

## 数据与产物

- 游戏资源、密钥、签名、存档和唯一输入材料只放 `local/`，不得放入可清理的 `out/`。
- 构建、探针输出、截图、日志和旧 exe 备份属于 `out/`；可删除，但删除前核对绝对路径，保留当前交接所需的少量证据。
- 不新增逐轮交接、重复状态表和复述同一实验的文档。新结论更新现有交接、输入说明或证据文件。

## 当前基线

- 安装版：`F4BF82B64BF2AD1A6B5B7DD0528163820CC3BE0A5979BFFE822C405B23535714`
- 补丁链：`0001–0034`，其中 `0029`、`0030` 不在链内。
- 当前已验证：世界移动、NPC 对话选项、主菜单/暂停菜单、角色页签、装备/技能类别、门进入/近距出口、商人商品行。
- 当前未完成：铁匠 NPC 全菜单、商人/工匠页签鼠标切换、开关/滑块、战利品箱、拾取、地牢/portal、技能鼠标方向、完整 0027 焦点门控。
