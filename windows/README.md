# Windows 运行时（ScarletNX + FSR1）

Windows 路径基于本地修改的 ScarletNX 源码运行 Diablo III，包含最终呈现的 FSR1 画质增强、实验性场景分层和原生键盘鼠标输入。实验是否启用及验证范围见状态说明。该目录自带源码工作树入口、补丁链、开发工具、逆向探针与全部 Windows 文档。

- [构建](docs/BUILD.md)
- [发行记录](docs/RELEASE.md)
- [当前验收与待完成项](docs/STATUS.md)
- [KBM 当前交接](docs/HANDOFF-20261104-CURRENT.md)
- [KBM 操作说明](docs/KBM-INPUT-GUIDE.md)
- [跨平台逆向过程与踩坑](../docs/REVERSE-ENGINEERING.md)

上游源码在 `source/ScarletNX-src/`（不入 Git，需按补丁链重放重建），补丁链入口 `patches/base.json`，构建输出在仓库根 `out/windows/`。2026-11-11 本机链可重放至 `0146`；`0145-scene-fsr-before-ui.patch` 和新增的 `0146-settings-option-tests.patch` 当前均为未跟踪文件，单独克隆已有提交不会取得它们。`0146` 只修正测试断言，现有安装仍为 `0145`。仓库路径含括号，构建使用无括号 junction `D:\workspace\Diablo-kbm`。

```powershell
Set-Location D:\workspace\Diablo-kbm
. .\windows\tools\Activate.ps1
.\windows\tools\Build.ps1
```

实际游戏测试另用 `windows/tools/Launch-Background.ps1`，并遵循仓库约定核对进程与测试窗口。

游戏资源、密钥、签名和存档只在 `local/` 与已安装目录使用，不进入本仓库。
