# ScarletNX Windows 补丁

`reference/ScarletNX-src/` 是本地上游检出，不纳入主仓库。此目录保留可重建当前 Windows FSR 版本所需的完整源码差异。

- 上游：<https://github.com/scarletnx/ScarletNX>
- 基线提交：`dbf8915965367e8a9616b19e5a0c1eddafaf28f3`
- 补丁：`0001-fsr1-present-stats.patch`
- 补丁 SHA-256、13 个结果文件的 LF 规范化 SHA-256 与基线元数据：`base.json`。

补丁包含 EASU/RCAS 着色器和 Vulkan 集成、异步录制描述符兼容、图像布局回退、资源寿命与翻转修复，以及 `upscaler` 设置、着色器构建规则、`vk_sc_view` 导出，和默认关闭的 `SNX_PRESENT_STATS` 呈现节奏统计（由环境变量开启，仅用于诊断）。包含 8 个已有文件的修改和 5 个新增文件；没有把临时构建、缓存、密钥或游戏资源写入补丁。

在主项目根目录准备上游检出并应用：

```powershell
git clone https://github.com/scarletnx/ScarletNX.git reference/ScarletNX-src
git -C reference/ScarletNX-src checkout dbf8915965367e8a9616b19e5a0c1eddafaf28f3
.\patches\windows\Apply-Patches.ps1 -CheckOnly
.\patches\windows\Apply-Patches.ps1
.\tools\windows-dev\Build.ps1
```

已有检出时不要重新 clone 或覆盖源码。脚本核对基线提交和补丁校验值，先检查可应用性；已完整应用时直接返回，不重置工作树，不提交或推送，不覆盖不匹配的修改。

本次补丁已在临时目录中对 `git archive` 导出的纯基线源码执行 `git apply --check`、实际应用和反向检查；应用后的 13 个文件与当前源码逐文件比较一致（统一换行后）。原工作树未被验证过程修改。

构建环境与输出目录见 [Windows 工具说明](../../tools/windows-dev/README.md)。上游为 GPL-3.0-or-later；AMD FSR 算法许可保留在 [AMD-FSR1-LICENSE.txt](../../licenses/AMD-FSR1-LICENSE.txt)。
