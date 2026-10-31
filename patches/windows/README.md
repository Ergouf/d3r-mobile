# ScarletNX Windows 补丁

`reference/ScarletNX-src/` 是本地上游检出，不纳入主仓库。此目录保留可重建当前 Windows FSR 版本所需的完整源码差异。

- 上游：<https://github.com/scarletnx/ScarletNX>
- 基线提交：`dbf8915965367e8a9616b19e5a0c1eddafaf28f3`
- 补丁：`0001-fsr1-present-stats.patch`、`0002-mouse-steer.patch`
- 补丁 SHA-256、14 个结果文件的 LF 规范化 SHA-256 与基线元数据：`base.json`。

`0002-mouse-steer.patch` 在 `0001` 之后应用，加入 `mouse_steer` 设置：鼠标位置驱动 1P 左摇杆，左键 A、右键 B、中键 X、侧键 Y/L；开启时鼠标不再当触摸屏。它只改 `src/nx/runtime/platform/backend/sdl3.c` 和 `src/nx/runtime/settings.txt`，默认关闭，不影响手柄和原有键盘映射。

`0003-native-bridge.patch` 在 `0002` 之后应用，加入运行时内的 guest 调用桥（`runtime/native_input.c/.h`、`main.c`、`rtapi.c`、`svc.c`、`CMakeLists.txt`）：队列 + 在游戏线程的 `rt_poll` 上执行 + 独立 guest 栈。自检默认关闭，桥不改变默认行为；`mouse_steer` 同时关闭手指触摸事件，避免鼠标点击又被游戏当成触摸。

补丁包含 EASU/RCAS 着色器和 Vulkan 集成、异步录制描述符兼容、图像布局回退、资源寿命与翻转修复，以及 `upscaler` 设置、着色器构建规则、`vk_sc_view` 导出、全屏启动前隐藏窗口、显示后再进入全屏，和默认关闭的 `SNX_PRESENT_STATS` 呈现节奏统计（由环境变量开启，仅用于诊断）。包含 9 个已有文件的修改和 5 个新增文件；没有把临时构建、缓存、密钥或游戏资源写入补丁。

在主项目根目录准备上游检出并应用：

```powershell
git clone https://github.com/scarletnx/ScarletNX.git reference/ScarletNX-src
git -C reference/ScarletNX-src checkout dbf8915965367e8a9616b19e5a0c1eddafaf28f3
.\patches\windows\Apply-Patches.ps1 -CheckOnly
.\patches\windows\Apply-Patches.ps1
.\tools\windows-dev\Build.ps1
```

已有检出时不要重新 clone 或覆盖源码。脚本核对基线提交和补丁校验值，先检查可应用性；已完整应用时直接返回，不重置工作树，不提交或推送，不覆盖不匹配的修改。
应用与检查使用 `git apply --ignore-whitespace`，兼容 Windows 检出的 CRLF 行尾。

本次补丁已在临时目录中对 `git archive` 导出的纯基线源码执行 `git apply --check`、实际应用和反向检查；应用后的 14 个文件与当前源码逐文件比较一致（统一换行后）。原工作树未被验证过程修改。

构建环境与输出目录见 [Windows 工具说明](../../tools/windows-dev/README.md)。上游为 GPL-3.0-or-later；AMD FSR 算法许可保留在 [AMD-FSR1-LICENSE.txt](../../licenses/AMD-FSR1-LICENSE.txt)。
