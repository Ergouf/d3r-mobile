# Windows 构建与依赖

Windows 使用本地修改的 ScarletNX 源码，位置为 `reference/ScarletNX-src/`。固定上游提交为 `dbf8915965367e8a9616b19e5a0c1eddafaf28f3`；该路径保留独立 Git 工作树和本地 FSR 修改。状态见 [当前验收](../STATUS.md)，KBM 当前状态见 [键鼠交接](HANDOFF-20261104-CURRENT.md)，成品见 [发行记录](RELEASE.md)。

## 工具链

当前机器使用 `D:\workspace\msys2\msys64` 的 MSYS2 CLANG64 环境：

| 组件 | 已验证版本 |
| --- | --- |
| Clang / LLVM / LLD | 23.1.3 |
| CMake / Ninja / NASM | 4.4.4 / 1.13.2 / 3.02 |
| Vulkan headers / loader / validation layers / utility libraries | 1.4.363 开发组件 |
| glslang / SPIRV-Tools | 16.6.0 / 2026.4 |

这是 MSYS2 开发组件组合，没有运行 LunarG SDK 安装器。GPU 运行时仍由 Intel 驱动提供，设备 API 为 Vulkan `1.3.293`；更高版本头文件不会升级驱动。

## 构建与依赖验收

在项目根 PowerShell 运行：

```powershell
. .\tools\windows-dev\Activate.ps1
.\tools\windows-dev\Test-Dependencies.ps1 -OutputPath .\out\windows\dependencies
.\tools\windows-dev\Build.ps1 -Configure
```

后续增量构建不加 `-Configure`。使用其他安装路径时传 `-MsysRoot`；源码路径可传 `-SourcePath`。脚本只设置当前进程环境，不永久改系统 PATH，也不混用另一套 llvm-mingw 的 `env.ps1`。

构建入口通过真正的 CLANG64 登录 shell 调用上游 `default` preset。CPM 下载固定依赖，配置和缓存由上游 CMake 管理。首次构建或清理生成目录后，按上游 [Windows 构建说明](../../reference/ScarletNX-src/docs/BUILD.md) 重新配置。

构建和测试产物统一集中在 `out/windows/`，主程序为 `out/windows/build-kbm/scarletnx.exe`；`dependencies/` 放依赖验收输出、`packages/` 放打包过程文件、`releases/` 放发行输出。不要把 guest 资源、密钥或唯一存档放在这些可清理目录。

依赖验收编译并链接 Vulkan C 程序，编译 GLSL、执行 `spirv-val`，显式启用 Khronos 验证层并创建 Intel Arc 逻辑设备及着色器模块。它不执行计算着色器，也不测游戏帧率。

## 运行与配置

当前安装入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`，直接启动运行时；`Launch.cmd` 仍保留。旧 `D:\Program Files` 安装已迁移删除。重新部署时使用完整解压的便携运行目录，通过其中 `Launch.cmd` 启动；仅复制 `scarletnx.exe` 不会携带游戏资源或导入库。

发行默认值：

```ini
[Display]
fullscreen=1
language=15
[Graphics]
resolution=1
upscaler=1
shadows=1
vsync=1
async_pipelines=0
[Performance]
fps_limit=game
[Controllers]
gamepad_swap_ab=1
gamepad_map=west:X north:Y
[Debug]
vk_validation=0
profile=0
diag=0
```

FSR1 EASU 放大后使用 RCAS，衰减 1.5 stops；0 最强，数值增大则减弱。内部 1×和阴影保持原设置。`upscaler=0` 可切回双线性做同场景对照。

F11 / Alt+Enter 切换全屏，F2 打开运行时菜单；游戏内 `Esc` 是返回/关闭当前界面，退出程序通过 F2 菜单。键鼠与手柄映射见 [KBM 操作说明](KBM-INPUT-GUIDE.md)。

## 验证口径

已完成相关 10 项 CTest、三份 FSR SPIR-V 验证、两次 3K 全屏及窗口切换验证。实战性能测试应关闭验证层，分别记录原生/guest 提交与独立上屏帧率。当前版本没有帧生成，不把 120Hz 当作 120 个不同帧。

当前 120Hz 下严重卡顿仍在诊断，FSR 最终实战验收未完成。既有构建、启动和验证层检查不能作为卡顿已修复的证据，最新短窗口对照见 [状态](../STATUS.md)。

游戏资源和提取输入只放本地目录；发布包省略日志、JIT/着色器缓存、原始 XCI/NCA 和密钥。重新打包后应全量检查 ZIP CRC、文件 SHA-256、整体 SHA-256，并从干净解压副本验证启动。

本地 Windows 存档分别保存在 `local/saves/windows-current/` 与 `local/saves/windows-original/`，用于保留当前与原包制作时的不同状态，不自动互相覆盖。原始游戏输入和提取数据集中在 `local/assets/`，密钥在 `local/keys/`。当前 `D:\Games\DiabloIII` 安装保持独立，也是当前唯一完整运行副本；工作区 ZIP 归档已作为重复副本清理，重打包时需用 `--source` 指定新的基线 ZIP。
