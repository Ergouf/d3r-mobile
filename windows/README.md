# Windows 运行时（ScarletNX + FSR1）

Windows 路径基于本地修改的 ScarletNX 源码运行 Diablo III，提供最终呈现的 FSR1 画质增强和原生键盘鼠标输入。该目录自带源码工作树入口、补丁链、开发工具、逆向探针与全部 Windows 文档。

- [构建](docs/BUILD.md)
- [发行记录](docs/RELEASE.md)
- [当前验收与待完成项](docs/STATUS.md)
- [KBM 当前交接](docs/HANDOFF-20261104-CURRENT.md)
- [KBM 操作说明](docs/KBM-INPUT-GUIDE.md)

上游源码在 `source/ScarletNX-src/`（不入 Git，可用补丁链重放重建），补丁链入口 `patches/base.json`，构建输出在仓库根 `out/windows/`。仓库路径含括号，构建使用无括号 junction `D:\workspace\Diablo-kbm`。

```powershell
. .\windows\tools\Activate.ps1
.\windows\tools\Build.ps1
.\windows\tools\Launch-Background.ps1
```

游戏资源、密钥、签名和存档只在 `local/` 与已安装目录使用，不进入本仓库。
