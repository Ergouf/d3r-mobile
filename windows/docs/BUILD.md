# Windows 构建与依赖

Windows 使用本地修改的 ScarletNX 源码，位置为 `windows/source/ScarletNX-src/`。固定上游提交为 `dbf8915965367e8a9616b19e5a0c1eddafaf28f3`；该路径保留独立 Git 工作树和本地 FSR 修改。状态见 [当前验收](STATUS.md)，KBM 当前状态见 [键鼠交接](HANDOFF-20261104-CURRENT.md)，成品见 [发行记录](RELEASE.md)。

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

在无括号 junction 下的项目根 PowerShell 运行（不存在时按 [工具说明](../tools/README.md) 创建）：

```powershell
Set-Location D:\workspace\Diablo-kbm
. .\windows\tools\Activate.ps1
.\windows\tools\Test-Dependencies.ps1 -OutputPath .\out\windows\dependencies
.\windows\tools\Build.ps1 -Configure
```

后续增量构建不加 `-Configure`。使用其他安装路径时传 `-MsysRoot`；源码路径可传 `-SourcePath`。脚本只设置当前进程环境，不永久改系统 PATH，也不混用另一套 llvm-mingw 的 `env.ps1`。

仓库真实路径含括号（`D:\workspace\Diablo(fegnjl)`），CMake 生成的 settingsgen 命令经 `cmd` 解析括号会失败（`'D:\workspace\Diablo' is not recognized`）。构建必须从无括号 junction `D:\workspace\Diablo-kbm` 进入，并在该路径下运行上述脚本；CMake 缓存也绑定二进制目录路径，移动或改名后需删除 `out/windows/build` 重新配置。

构建入口通过真正的 CLANG64 登录 shell 调用上游 `default` preset。CPM 下载固定依赖，配置和缓存由上游 CMake 管理。首次构建或清理生成目录后，按上游 [Windows 构建说明](../source/ScarletNX-src/docs/BUILD.md) 重新配置。

补丁按 `windows/patches/base.json` 顺序恢复并校验，不能直接遍历目录。2026-11-11 本机重放 132 阶段通过；新增 `0146` 只更新测试断言，安装运行时仍为 `0145`。`0145-scene-fsr-before-ui.patch` 和 `0146-settings-option-tests.patch` 均为未跟踪文件：在将它们纳入 Git 之前，单独克隆已有提交不能重建完整链。

构建和测试产物统一集中在 `out/windows/`，主程序为 `out/windows/build/scarletnx.exe`；`dependencies/` 放依赖验收输出、`packages/` 放打包过程文件、`releases/` 放发行输出。不要把 guest 资源、密钥或唯一存档放在这些可清理目录。

依赖验收编译并链接 Vulkan C 程序，编译 GLSL、执行 `spirv-val`，显式启用 Khronos 验证层并创建 Intel Arc 逻辑设备及着色器模块。它不执行计算着色器，也不测游戏帧率。

## 运行与配置

`0145` 包含显式场景分层实验：启动前设置 `SNX_SCENE_SCALE=0.75`、`SNX_SCENE_FSR=1`，传入 `--resolution=1 --upscaler=0`；仅场景附件降采样，在识别的游戏合成 draw 中执行内置 FSR，再按原尺寸绘制 UI/文字。不要同时启用最终全帧 FSR。共享深度在场景/UI 使用前双向同步，含写深度的 3D 预览与模板保持。未设置上述变量时沿用正常画面配置；该实验的城镇/物品栏与 GPU 像素证据见当前交接，省电和独立上屏收益尚未验证。

当前安装入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`，直接启动运行时；`Launch.cmd` 仍保留。旧 `D:\Program Files` 安装已迁移删除。重新部署时使用完整解压的便携运行目录，通过其中 `Launch.cmd` 启动；仅复制 `scarletnx.exe` 不会携带游戏资源或导入库。

发行打包器默认值（不是现有安装的当前 INI）：

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

FSR1 EASU 放大后使用 RCAS，衰减 1.5 stops；0 最强，数值增大则减弱。2026-11-11 核对的现有安装 INI 为 `resolution=1.75`、`upscaler=1`、`shadows=1`；后台启动器也通过命令行指定 1.75×。发行包的 1× 默认值不会自动覆盖现有安装。`upscaler=0` 可切回双线性做同场景对照。

F11 / Alt+Enter 切换全屏，F2 打开运行时菜单；游戏内 `Esc` 是返回/关闭当前界面，退出程序通过 F2 菜单。键鼠与手柄映射见 [KBM 操作说明](KBM-INPUT-GUIDE.md)。

## 验证口径

已完成相关 10 项 CTest、三份 FSR SPIR-V 验证、两次 3K 全屏及窗口切换验证。实战性能测试应关闭验证层，分别记录原生/guest 提交与独立上屏帧率。当前版本没有帧生成，不把 120Hz 当作 120 个不同帧。

120Hz 长期表现和 FSR 最终实战验收未完成。重启及驱动更新后的短窗未复现此前严重卡顿，但不足以证明长期问题已解决；对照见 [状态](STATUS.md)。

游戏资源和提取输入只放本地目录；发布包省略日志、JIT/着色器缓存、原始 XCI/NCA 和密钥。重新打包后应全量检查 ZIP CRC、文件 SHA-256、整体 SHA-256，并从干净解压副本验证启动。

本地 Windows 存档分别保存在 `local/saves/windows-current/` 与 `local/saves/windows-original/`，用于保留当前与原包制作时的不同状态，不自动互相覆盖。原始游戏输入和提取数据集中在 `local/assets/`，密钥在 `local/keys/`。当前 `D:\Games\DiabloIII` 安装保持独立，也是当前唯一完整运行副本；工作区 ZIP 归档已作为重复副本清理，重打包时需用 `--source` 指定新的基线 ZIP。
