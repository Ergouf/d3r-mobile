# Diablo III 兼容运行项目

本项目包含两个独立路径：Android ARM64 原生兼容层，以及基于 ScarletNX 的 Windows 运行时与 FSR1 增强。当前验收状态统一见 [docs/STATUS.md](docs/STATUS.md)，Windows 原生键鼠入口见 [KBM 交接](docs/windows/HANDOFF-20261104-CURRENT.md)。

远程仓库：[Ergouf/d3r-mobile](https://github.com/Ergouf/d3r-mobile)。

## 入口

| 任务 | 文档 |
| --- | --- |
| 当前结果、限制与待完成项 | [状态与验收](docs/STATUS.md) |
| Android 构建、资源和存档 | [Android 构建](docs/android/BUILD.md) |
| Android 固定依赖及许可 | [Android 依赖](docs/android/DEPENDENCIES.md) |
| Android 源码接口与保留约束 | [Android 架构](docs/android/ARCHITECTURE.md) |
| Windows 工具链与构建 | [Windows 构建](docs/windows/BUILD.md) |
| Windows 成品位置及校验值 | [Windows 发行记录](docs/windows/RELEASE.md) |
| Windows 当前 KBM 交接 | [键鼠交接](docs/windows/HANDOFF-20261104-CURRENT.md) |
| Windows 键盘/鼠标操作 | [KBM 操作说明](docs/windows/KBM-INPUT-GUIDE.md) |
| Windows Quick Resume | [快速恢复说明](docs/windows/QUICK-RESUME.md) |

Windows 当前安装入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`（直接启动运行时，无控制台窗口），`Launch.cmd` 仍保留；完整 ZIP 归档已作为安装目录的重复副本清理，重打包时需显式指定基线 ZIP。当前版本默认 FSR1、原生 1×、阴影与中文，没有帧生成。120Hz 下严重卡顿正在诊断，FSR 最终实战验收尚未完成。Android 已进入第一章，但持续稳定 60 FPS、完整任务链和 OEM 生成帧仍未验收。

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `d3-android/host/` | Horizon 服务、ARM64 guest 接入、音频、内容、输入和同步 |
| `d3-android/app/` | Android Activity、触控、手柄与画面设置 |
| `d3-android/gpu/` | Eden Vulkan 桥接、固定依赖补丁及着色器工具 |
| `d3-android/tests/` | 保留的 native、Python、Java 回归测试源码 |
| `d3-android/tools/` | Android 构建、资源处理与诊断工具 |
| `reference/ScarletNX-src/` | Windows 上游源码工作树，保留本地 FSR 修改 |
| `reference/eden/`、`d3-android/gpu/third_party/` | 本地固定版本的第三方源码，默认不入本仓库 Git |
| `tools/windows-dev/` | Windows 环境、依赖验收、构建及打包工具 |
| `docs/` | 统一维护的状态、构建、依赖和发行说明 |
| `assets/marketing/` | 保留的宣传图、原图与配套素材 |
| `local/` | 本地游戏输入、guest、密钥、存档及不可重建材料，不入 Git |
| `out/android/` | Android 各 profile、host、GPU、驱动工具和 probe 输出 |
| `out/windows/` | Windows 构建、依赖验收、包与发行输出 |
| `reference/legacy-recovery/` | 保留的早期源码恢复快照，不作为当前构建入口 |

不要把唯一 guest、签名文件或存档放在临时构建目录。新增说明合并到对应平台文档，避免继续创建逐轮交接和重复状态报告。临时日志、截图、解压副本与旧构建可清理，回归测试源码保留。

## 开发规则

代码探索优先使用 Serena 符号概要、查询和引用；符号上下文不足时再用定向 `rg` 和局部读取。本地服务查询入口为 `d3-android/tools/serena_query.py`。

保持游戏资源、设备数据与代码分离。更新设备应用时复用正确签名并备份存档；当前源码与测试细节见平台构建文档。

## 许可证

原创 Android 兼容层按 [GNU AGPL-3.0](LICENSE) 发布。静态链接的 Eden 为 GPL-3.0、Sirit 为 AGPL-3.0，分发时保留第三方版权和许可证，并提供对应源码。Windows ScarletNX 为 GPL-3.0-or-later，FSR1 算法为 AMD MIT 许可；各组件保留自己的授权。

游戏数据、固件、密钥、签名私钥和厂商驱动只在本地使用，不属于本仓库或其开源授权。第三方版本和许可见 [Android 依赖](docs/android/DEPENDENCIES.md) 与 Windows 源码/发行包的许可证。本项目与 Blizzard Entertainment、Nintendo 无隶属关系。
