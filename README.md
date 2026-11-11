# Diablo III 兼容运行项目

本项目包含两个按平台分开的独立路径：Android ARM64 原生兼容层（`android/`），以及基于 ScarletNX 的 Windows 运行时与 FSR1 增强（`windows/`）。验收状态分别见 [Android 状态](android/docs/STATUS.md)、[Windows 状态](windows/docs/STATUS.md) 和 [状态索引](docs/STATUS.md)；Windows 原生键鼠入口见 [KBM 交接](windows/docs/HANDOFF-20261104-CURRENT.md)。

远程仓库：[Ergouf/d3r-mobile](https://github.com/Ergouf/d3r-mobile)。

## 入口

| 任务 | 文档 |
| --- | --- |
| 当前结果、限制与待完成项 | [Android 状态](android/docs/STATUS.md)、[Windows 状态](windows/docs/STATUS.md) |
| Android 构建、资源和存档 | [Android 构建](android/docs/BUILD.md) |
| Android 固定依赖及许可 | [Android 依赖](android/docs/DEPENDENCIES.md) |
| Android 源码接口与保留约束 | [Android 架构](android/docs/ARCHITECTURE.md) |
| 目录约定 | [目录结构](docs/STRUCTURE.md) |
| 两平台逆向过程、常见坑及证据入口 | [逆向过程与踩坑](docs/REVERSE-ENGINEERING.md) |
| Windows 工具链与构建 | [Windows 构建](windows/docs/BUILD.md) |
| Windows 成品位置及校验值 | [Windows 发行记录](windows/docs/RELEASE.md) |
| Windows 当前 KBM 交接 | [键鼠交接](windows/docs/HANDOFF-20261104-CURRENT.md) |
| Windows 键盘/鼠标操作 | [KBM 操作说明](windows/docs/KBM-INPUT-GUIDE.md) |
| Windows Quick Resume | [快速恢复说明](windows/docs/QUICK-RESUME.md) |

Windows 当前安装入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`（直接启动运行时，无控制台窗口），`Launch.cmd` 仍保留；完整 ZIP 归档已作为安装目录的重复副本清理，重打包时需显式指定基线 ZIP。2026-11-11 核对的安装 INI 为 `resolution=1.75`、FSR1 和阴影开启；后台启动脚本也显式传入 1.75×。发行包制作的默认值是 1×，与现有安装配置不同，当前没有帧生成。120Hz 的长期表现与 FSR 实战仍待验收。Android 已进入第一章，但持续稳定 60 FPS、完整任务链和 OEM 生成帧仍未验收。

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `android/host/` | Horizon 服务、ARM64 guest 接入、音频、内容、输入和同步 |
| `android/app/` | Android Activity、触控、手柄与画面设置 |
| `android/gpu/` | Eden Vulkan 桥接、固定依赖补丁及着色器工具 |
| `android/tests/` | 保留的 native、Python、Java 回归测试源码 |
| `android/tools/` | Android 构建、资源处理与诊断工具 |
| `android/docs/`、`android/third_party/eden/` | Android 文档与本地固定第三方源码（后者默认不入 Git） |
| `windows/source/ScarletNX-src/` | Windows 上游源码工作树，保留本地 FSR 修改（默认不入 Git） |
| `windows/docs/` | Windows 构建、发行、KBM 交接与状态 |
| `android/gpu/third_party/` | GPU 侧本地固定第三方源码，默认不入本仓库 Git |
| `windows/tools/` | Windows 环境、依赖验收、构建及打包工具 |
| `windows/patches/` | Windows 补丁链与 `base.json` 阶段索引（按序应用到上游源码） |
| `windows/d3-re/` | Windows 逆向探针、运行时会话驱动与证据工具 |
| `out/windows/kbm/` | Windows KBM 会话证据、候选构建与安装备份 |
| `docs/` | 跨平台状态索引、目录约定和逆向踩坑索引 |
| `assets/marketing/` | 保留的宣传图、原图与配套素材 |
| `local/` | 本地游戏输入、guest、密钥、存档及不可重建材料，不入 Git |
| `out/android/` | Android 各 profile、host、GPU、驱动工具和 probe 输出 |
| `out/windows/` | Windows 构建、依赖验收、包与发行输出 |
| `reference/legacy-recovery/` | 保留的早期源码恢复快照，不作为当前构建入口 |

不要把唯一 guest、签名文件或存档放在临时构建目录。新增说明合并到对应平台文档，避免继续创建逐轮交接和重复状态报告。临时日志、截图、解压副本与旧构建可清理，回归测试源码保留。

## 开发规则

代码探索优先使用 Serena 符号概要、查询和引用；符号上下文不足时再用定向 `rg` 和局部读取。本地服务查询入口为 `android/tools/serena_query.py`。

保持游戏资源、设备数据与代码分离。更新设备应用时复用正确签名并备份存档；当前源码与测试细节见平台构建文档。

## 许可证

原创 Android 兼容层按 [GNU AGPL-3.0](LICENSE) 发布。静态链接的 Eden 为 GPL-3.0、Sirit 为 AGPL-3.0，分发时保留第三方版权和许可证，并提供对应源码。Windows ScarletNX 为 GPL-3.0-or-later，FSR1 算法为 AMD MIT 许可；各组件保留自己的授权。

游戏数据、固件、密钥、签名私钥和厂商驱动只在本地使用，不属于本仓库或其开源授权。第三方版本和许可见 [Android 依赖](android/docs/DEPENDENCIES.md) 与 Windows 源码/发行包的许可证。本项目与 Blizzard Entertainment、Nintendo 无隶属关系。
