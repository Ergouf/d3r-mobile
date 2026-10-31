# Windows 开发与打包工具

源码位于 `reference/ScarletNX-src/`，本目录保存可复用脚本。MSYS2 CLANG64 工具链默认安装在项目外的 `D:\workspace\msys2\msys64`。Vulkan 开发组件来自 MSYS2；显卡运行时由已安装的 Intel 驱动提供。

当前安装入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`，直接启动运行时且没有控制台窗口；`Launch.cmd` 仍保留。旧 `D:\Program Files` 安装已迁移删除。120Hz 严重卡顿仍在诊断，FSR 最终实战验收尚未完成；运行与性能状态见 [STATUS.md](../../docs/STATUS.md)。

从项目根目录运行：

```powershell
. .\tools\windows-dev\Activate.ps1
.\tools\windows-dev\Test-Dependencies.ps1
.\tools\windows-dev\Build.ps1
```

`Activate.ps1` 只修改当前进程的环境变量，不改系统 PATH 或权限。可传 `-MsysRoot` 选择工具链。`Build.ps1` 默认输出到 `out/windows/build/`；缓存不存在时自动配置，也可用 `-Configure` 重新配置或用 `-BuildPath` 指定其他输出目录。构建在真正的 CLANG64 shell 中执行，不混用另一套 llvm-mingw 环境。

`Test-Dependencies.ps1` 将 C 编译/链接、GLSL 编译、SPIR-V 验证及 Intel Vulkan 设备创建结果写入 `out/windows/dependencies/`，可用 `-OutputPath` 改位置。该检查不执行着色器，也不测量游戏帧率。

## 呈现诊断

`Get-ActiveDisplayMode.ps1 -AsJson` 读取活动信号的精确刷新率；`Set-ActiveDisplayRefresh.ps1 -RefreshHz 60`（或 `120`）仅临时切换已支持的主屏模式，先保存恢复记录并验证结果，不写入注册表。帧时间对照须串行运行，期间不编译。

`vulkan-present-probe.c` 与 `dxgi-present-probe.c` 是不依赖游戏的原生清屏探针，默认主屏尺寸、60fps 提交目标，接受 `--seconds`、`--fps` 和 `--output`。Vulkan 另支持 `--immediate`、只查询能力的 `--check-exclusive`，以及获取失败即退出的 `--exclusive`；实际独占测试须将窗口置于前台。两者的终端/CSV 均为主机调用计时，实际上屏间隔另用 PresentMon 采集。`analyze_presentmon.py` 汇总当前 PresentMon 默认 CSV 格式，保留未显示帧和缺失值；不接受旧 `--v1_metrics` 格式。

`Run-PresentMon.ps1 -Tag <名> -Seconds <秒>` 以管理员权限启动 PresentMon 记录 `01001B300B9BE000.exe`（Windows 需要管理员或 Performance Log Users 组才能开启 ETW 会话），CSV 落在 `out/windows/diagnostics/`。`Capture-Probe.ps1 -Tag <名> -Exe <探针> -Seconds <秒>` 串行采集探针与 PresentMon；`Capture-Screen.ps1 -OutPath <png> [-CropX -CropY -CropW -CropH]` 以 DPI 感知方式抓取原生像素。

`Focus-Game.ps1 -ProcessId <pid> [-Keys <SendKeys>]` 通过 AttachThreadInput 把游戏窗口切到前台并校验结果，用于无人值守回归；`SNX_PRESENT_STATS=1` 让运行时输出呈现节奏统计，默认关闭。

## 打包

```powershell
python .\tools\windows-dev\package_fsr_release.py --self-test
python .\tools\windows-dev\package_fsr_release.py --source <完整资源包.zip> --expected-runtime-sha256 <已验收程序的SHA256>
```

工作区中的默认基线 ZIP 已作为安装目录重复副本清理；打包时必须通过 `--source` 或环境变量 `DIABLO_RELEASE_ZIP` 指定完整资源包。默认运行时为 `out/windows/build/scarletnx.exe`，可用 `--runtime` 另选。运行时 SHA-256 由当前文件计算，`--expected-runtime-sha256` 是可选的验收身份约束。

新包输出到 `out/windows/releases/DiabloIII-Windows-2.7.7.92380-zhCN-Xbox-FSR1-repacked.zip`，完整校验报告和源码快照输出到 `out/windows/packages/`。输入基线、输出和已有文件均不会被覆盖。AMD 许可从 `licenses/AMD-FSR1-LICENSE.txt` 读取。设置按节更新，重复打包不会叠加 `upscaler` 等键。

默认逐条完整读取 ZIP，核对 CRC 和清单 SHA-256，不额外保留一份二十多 GB 的解压资源。需要实机测试副本时加 `--extract`，输出在报告目录的 `extracted/`。发布前写好校验记录；临时文件被同步程序占用时会短暂重试，再以不覆盖目标的复制方式发布并复核 SHA-256。复制回退会保留临时文件，并在报告中明确记录。

## 复制到交付目录

```powershell
.\tools\windows-dev\Install-Release.ps1 -SourcePath .\out\windows\releases\<成品>.zip -ExpectedSha256 <ZIP校验值>
```

该步骤复制 ZIP 交付包，默认交付目录沿用此前用户指定的 `D:\Program Files`，可用 `-DestinationDirectory` 改位置；游戏实际启动入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`，`Launch.cmd` 仍保留。收据默认在 `out/windows/packages/install-receipt.json`。脚本校验源文件和目标文件，保留源文件且拒绝覆盖。目标目录需要管理员权限时，请从已有管理员终端执行；脚本不会自动提权或更改系统目录权限。

## 活动显示模式取证

```powershell
.\tools\windows-dev\Get-ActiveDisplayMode.ps1 -AsJson
```

该脚本只读调用 `QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)`，返回每条活动显示路径的显卡、显示器、桌面尺寸、活动信号尺寸，以及原始分子/分母与计算 Hz。`PathRefreshRate` 是活动路径频率，`SignalVSyncRate` 是目标信号的垂直同步频率。两者均保留，避免把 CIM 的 `CurrentRefreshRate` 或整数舍入值当成物理信号频率。查询失败时才回退 `EnumDisplaySettingsEx`，并明确标记其只有整数频率、无法确认精确物理信号。脚本不调用更改模式接口，也不运行 GUI 或发送输入。

## 输入探针与无括号构建路径

`Post-GameInput.ps1` 直接向游戏窗口 PostMessage 键鼠，不抢前台：

```powershell
.\tools\windows-dev\Post-GameInput.ps1 -Key space
.\tools\windows-dev\Post-GameInput.ps1 -Key up -Repeat 3
.\tools\windows-dev\Post-GameInput.ps1 -Click '600,120'
.\tools\windows-dev\Post-GameInput.ps1 -Move '600,200'
```

方向键会自动带 extended 标志。`Capture-Window.ps1` 用 `PrintWindow` 抓窗口，不抢焦点；Vulkan 窗口可能返回旧帧，状态确认以桌面抓图（`Capture-Screen.ps1`）为准。

仓库路径含括号（例如 `Diablo(fegnjl)`）时，`settingsgen` 的 cmd 命令行会被截断。请建一个无括号 junction 并在那里构建：

```powershell
cmd /c mklink /J D:\workspace\Diablo-kbm "D:\workspace\Diablo(fegnjl)"
cd D:\workspace\Diablo-kbm
.\tools\windows-dev\Build.ps1 -Configure -SourcePath D:\workspace\Diablo-kbm\reference\ScarletNX-src -BuildPath D:\workspace\Diablo-kbm\out\windows\build-kbm
```

OpenSSL 外部工程在 `-j18` 下可能因依赖文件竞争失败；进入 `out/windows/build-kbm/openssl-build` 用 `make -j1 build_libs` 补跑后，再执行一次 `Build.ps1` 即可。
