# 仓库协作约定

## 代码探索

- 优先使用 Serena 的符号概要、符号查询、引用查询；符号级上下文不足时才读取完整文件。
- Serena MCP 地址为 `http://127.0.0.1:9144/mcp`，客户端为 `android/tools/serena_query.py`。已有服务直接复用，避免重复启动。
- 每会话调用一次 `initial_instructions`，再用 `get_current_config` 或符号查询确认项目已激活。
- `windows/source/ScarletNX-src` 被主仓库忽略，分析时必须单独激活该 Serena 项目；不能把主项目空结果当成源码不存在。
- 服务不可用时用隐藏窗口启动，日志写入 `out/`：

  ```powershell
  serena start-mcp-server --project "D:/workspace/Diablo(fegnjl)" --transport streamable-http --host 127.0.0.1 --port 9144 --enable-web-dashboard false --enable-gui-log-window false --open-web-dashboard false
  ```

- Serena 失败时先定位并修复；仍不可用时说明原因，按最小范围用其他方法继续，不能伪称使用了 Serena。

## 修改与验收

- 直接修改、运行相关测试并串行实机复测；发现问题后修复并重新验证。
- 不启动审核子代理。验证优先使用串行脚本探针。
- 不并发运行 Frida 探针；并发 attach 曾导致游戏退出。
- 编译成功、UI 高亮、`operate accepted` 或 `submit returned` 都不等于业务完成。必须有可观察结果，例如 place、物品/资源数量、HP、传送及 UI before/after。
- Windows 进程身份同时核对完整路径、启动时间和 SHA-256；PID 会被复用。
- 新的 Android 测试窗口开始前核对安装 APK/SO 哈希、进程身份、温度和外部供电状态，并确认上一轮游戏已经停止。

## Android 设备交互

- 2026-11-10 用户明确授权主代理自主完成 ADB 截图、视觉检查和 vivo 安装确认。安装框出现后，直接使用 ADB 检查并点击“同意”，不要求用户手动勾选，也不为此结束回合等待用户。
- 安装前点亮并解锁屏幕，确认 `dumpsys power` 中 `mWakefulness=Awake`。使用 `adb install -r` 覆盖同一 profile，不用卸载或清数据绕过确认。
- 设备安全界面或系统策略确实阻止脚本点击时，保存截图和 ADB 输出，继续可独立进行的工作；无法绕过时再向用户报告具体阻塞。
- 游戏只在实际测试窗口运行。测试成功、失败、超时、采样器异常或 ADB 传输中断时，都必须尝试 `am force-stop` 并核对进程已经退出。
- 编译、代码分析、等待、吃饭或休息期间保持游戏关闭，避免持续功耗和发热。设备 local 的采集脚本必须带退出清理逻辑。
- 截图、日志、帧时和诊断输出写入 `out/`；游戏资源、密钥、签名、存档和唯一输入材料只放 `local/`。

## Windows 游戏窗口

- 新启动统一使用 `windows/tools/Launch-Background.ps1`：1024×576、位置 `(40,40)`、后台、非置顶、`SWP_NOACTIVATE`。
- 不调用 `SetForegroundWindow` / `SetActiveWindow`，不设置 topmost，不把窗口拉回前台。
- 不使用真实光标或 `SendInput` 绕过后台窗口限制。脚本注入只用 SDL 事件、游戏线程调用和只读内存探针，产物写入 `out/`。

## 启动与片头

- 启动后不等片头 CG 或“按任意键”流程完成。确认是本次新启动、尚无世界 HUD 的标题/CG 后，立即发送一次 SDL `Space` 跳过：

  ```powershell
  python windows/d3-re/probe_sdl_key.py --pid <PID> --key space
  ```

- 以“主菜单”出现作为跳过成功判据。世界 HUD 加载后不要再发送 `Space` 充当跳过键。
- 片头最长可接近两分钟，不能让它进入帧率或功耗采样窗口。

## KBM 范围

- 目标是原生键盘、鼠标、世界点击、目标交互、游戏 UI 和菜单；键盘转 Npad、鼠标转摇杆或“改焦点再发 A”不能作为交付替代。
- 功能差距以 [KBM 当前交接](windows/docs/HANDOFF-20261104-CURRENT.md)、[功能差距表](windows/docs/KBM-PARITY-20261106.md)、[输入说明](windows/docs/KBM-INPUT-GUIDE.md)和[技术证据](windows/docs/KBM-RE-EVIDENCE.md)为准。
- `0029`、`0030` 已归档。Windows 补丁只按 `windows/patches/base.json` 的链应用。
- 仓库路径含括号；构建使用无括号 junction `D:\workspace\Diablo-kbm`。

## 文档与证据

- 不新增逐轮交接、重复状态表或同一实验的复述。Android 新结论更新 `android/docs/STATUS.md` 与 Android 构建/架构说明；Windows 新结论更新 `windows/docs/STATUS.md` 与当前 Windows 交接；跨平台概要放 `docs/STATUS.md`。
- `out/` 中的构建、截图、日志和旧二进制可清理；删除前核对绝对路径。
- 未实测的画质、帧率、正确性和省电收益标为候选或未验证，不能写成完成。
- AGENTS.md 只保存长期协作规则；会变化的安装 SHA、性能数据和未完成列表以 `docs/STATUS.md` 和对应交接为准。
