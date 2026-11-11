# 仓库协作约定

## 代码探索

- 优先使用 Serena 的符号概要、符号查询和引用查询；仅在符号上下文不足时读取完整文件。每会话调用一次 `initial_instructions`，并用 `get_current_config` 或符号查询确认项目已激活。
- Serena 地址为 `http://127.0.0.1:9144/mcp`，客户端为 `android/tools/serena_query.py`。复用已有服务；不可用时先定位并修复，仍失败才说明原因并在最小范围内使用其他方法。需要启动时使用隐藏窗口，日志写入 `out/`：

  ```powershell
  serena start-mcp-server --project "D:/workspace/Diablo(fegnjl)" --transport streamable-http --host 127.0.0.1 --port 9144 --enable-web-dashboard false --enable-gui-log-window false --open-web-dashboard false
  ```

- `windows/source/ScarletNX-src` 被主仓库忽略，分析它时必须单独激活该 Serena 项目，不能将主项目的空结果当作源码不存在。

## 修改与验收

- 直接修改，运行相关测试并串行实机复测；发现问题后修复并重新验证。验证优先使用串行脚本探针，不启动审核子代理，也不并发运行 Frida 探针。
- 编译成功、UI 高亮、`operate accepted` 或 `submit returned` 不等于业务完成。以地点、物品或资源数量、HP、传送、UI 前后变化等可观察结果验收。
- 新 Android 测试窗口前核对安装 APK/SO 哈希、进程身份、温度和外部供电，并确认上一轮游戏已停止。Windows 进程同时核对完整路径、启动时间和 SHA-256，不能只凭 PID。

## Android 设备

- 用户已授权自主使用 ADB 截图、视觉检查和处理 vivo 安装确认。安装未知来源应用时，直接用 ADB 检查界面并点击“同意”复选框及后续安装按钮，不等待用户手动操作。
- 安装前点亮并解锁屏幕，确认 `dumpsys power` 中 `mWakefulness=Awake`；用 `adb install -r` 安装或覆盖同一 profile，不卸载或清数据绕过确认。只有系统安全界面或策略确实阻止脚本操作时，才保存截图与 ADB 输出并报告具体阻塞，同时继续其他可独立工作。
- 游戏只在实际测试窗口运行；成功、失败、超时、采样异常或 ADB 中断时，都须尝试 `am force-stop` 并核对进程退出。编译、分析、等待或休息时保持游戏关闭；设备本地采集脚本必须带退出清理逻辑。
- 截图、日志、帧时和诊断输出放 `out/`；游戏资源、密钥、签名、存档和唯一输入材料只放 `local/`。

## Windows 游戏与 KBM

- 新启动统一使用 `windows/tools/Launch-Background.ps1`：1024×576、位置 `(40,40)`、后台、非置顶、`SWP_NOACTIVATE`。不调用 `SetForegroundWindow` / `SetActiveWindow`，不设置 topmost，也不使用真实光标或 `SendInput`；仅用 SDL 事件、游戏线程调用和只读内存探针，产物放 `out/`。
- 新进程处于无世界 HUD 的标题或 CG 时立即执行 `python windows/d3-re/probe_sdl_key.py --pid <PID> --key space` 跳过片头；以主菜单出现为成功判据，世界 HUD 加载后不得再把 `Space` 当跳过键。片头可能接近两分钟，不得纳入帧率或功耗采样。
- KBM 交付范围是原生键盘、鼠标、世界点击、目标交互、游戏 UI 和菜单；键盘转 Npad、鼠标转摇杆或改焦点后发送 A 不能替代。差距与证据以 [当前交接](windows/docs/HANDOFF-20261104-CURRENT.md)、[功能差距表](windows/docs/KBM-PARITY-20261106.md)、[输入说明](windows/docs/KBM-INPUT-GUIDE.md)和[技术证据](windows/docs/KBM-RE-EVIDENCE.md)为准。
- `0029`、`0030` 已归档；Windows 补丁只按 `windows/patches/base.json` 的链应用。构建使用无括号 junction `D:\workspace\Diablo-kbm`。

## 文档与证据

- 不新增逐轮交接、重复状态表或同一实验的复述。Android 结论更新 `android/docs/STATUS.md` 和构建/架构说明；Windows 结论更新 `windows/docs/STATUS.md` 和当前交接；跨平台概要放 `docs/STATUS.md`。
- 未实测的画质、帧率、正确性或省电收益只能标为候选或未验证。可清理 `out/` 中的构建、截图、日志和旧二进制，但删除前须核对绝对路径。
- AGENTS.md 只保存长期协作规则；安装 SHA、性能数据和未完成列表等变化状态放在 `docs/STATUS.md` 与对应交接中。
