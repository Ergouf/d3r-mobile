# 项目目录约定

Android 与 Windows 两条实现路径在仓库顶层按平台分开，源码、工具、补丁、文档和构建入口都放在各自的平台目录内；共享的状态索引、本地输入和可重建产物单独放置。当前状态见 [状态索引](STATUS.md)、[Android 状态](../android/docs/STATUS.md) 与 [Windows 状态](../windows/docs/STATUS.md)。

## 顶层布局

| 目录 | 内容 | 维护规则 |
| --- | --- | --- |
| `android/` | Android 实现：Horizon 兼容层、Java 外壳、Eden GPU 适配、构建工具、回归测试与 Android 文档 | 平台自包含；构建入口 `android/Makefile`、`android/build.sh`，文档在 `android/docs/` |
| `windows/` | Windows 实现：ScarletNX 上游源码工作树与本地 FSR/键鼠修改、补丁链、开发工具、逆向工具与 Windows 文档 | 平台自包含；补丁链入口 `windows/patches/base.json`，文档在 `windows/docs/` |
| `docs/` | 跨平台的状态索引、目录约定与[逆向过程和踩坑](REVERSE-ENGINEERING.md) | 平台状态写入对应文档；共性方法指向原始证据 |
| `reference/` | 其他本地/历史材料：`d3-symbols/` 符号查询、`legacy-recovery/` 早期源码快照、`d2r-mobile/` 与 `tools/` 本地资源工具 | 只在明确引用时使用；不作为当前构建入口 |
| `assets/marketing/` | 保留的宣传素材 | 测试截图进入 `out/` |
| `licenses/` | 额外许可材料 | 与对应源码一并维护 |
| `local/` | 游戏输入、guest、签名、存档、驱动 | 不入 Git；只读或明确备份，不能作为构建输出 |
| `out/` | 全部可重建产物 | `out/android/` 归 Android、`out/windows/` 归 Windows，互不混放 |

## Android 目录（`android/`）

| 路径 | 用途 |
| --- | --- |
| `android/host/` | Horizon 服务、ARM64 guest 接入、音频、内容、输入和同步 |
| `android/app/` | Android Activity、触控、手柄与画面设置 |
| `android/gpu/` | Eden Vulkan 桥接、固定依赖补丁及着色器工具 |
| `android/tests/` | 保留的 native、Python、Java 回归测试源码 |
| `android/tools/` | Android 构建、资源处理与诊断工具 |
| `android/docs/` | 构建、依赖、架构说明与 [Android 状态](../android/docs/STATUS.md) |
| `android/third_party/eden/` | 本地固定的 Eden 第三方源码，默认不入 Git；由 `android/gpu/patches/` 与依赖清单恢复 |

生成头位于 `out/android/generated/include/`，GPU 构建和 coverage 检查自动补齐缺失或过期头文件。旧的 `android/gpu/gen/`、`android/build/` 和逐轮证据目录不再作为工具输入。Python 缓存可放到 `out/android/python-cache`。

## Windows 目录（`windows/`）

| 路径 | 用途 |
| --- | --- |
| `windows/source/ScarletNX-src/` | 上游源码工作树（固定提交加本地 FSR/键鼠修改），不入 Git，可用补丁链重放重建 |
| `windows/patches/` | 补丁链、`base.json` 阶段索引与 `Apply-Patches.ps1` |
| `windows/tools/` | Windows 环境、依赖验收、构建、启动、打包与测试工具 |
| `windows/d3-re/` | Windows 逆向探针、运行时会话驱动与证据工具 |
| `windows/docs/` | 构建、发行、KBM 交接与 [Windows 状态](../windows/docs/STATUS.md) |

Windows 构建使用 `windows/tools/Build.ps1`，输出到 `out/windows/build/`；启动用 `windows/tools/Launch-Background.ps1`。仓库路径含括号，构建使用无括号 junction `D:\workspace\Diablo-kbm`。

## 通用规则

固定依赖清单与补丁文件名中的日期代表版本基线，不属于临时报告。不要仅按文件名包含日期就删除源码、补丁、存档或签名。

目录整理不改变原生业务实现，也不删除 `tests/` 下的回归源码。新增日志、截屏、测试副本和构建中间文件统一写入 `out/`。

## Windows KBM 文档

- 当前交接：[windows/docs/HANDOFF-20261104-CURRENT.md](../windows/docs/HANDOFF-20261104-CURRENT.md)
- 操作说明：[windows/docs/KBM-INPUT-GUIDE.md](../windows/docs/KBM-INPUT-GUIDE.md)
- 技术证据与已知错误：[windows/docs/KBM-RE-EVIDENCE.md](../windows/docs/KBM-RE-EVIDENCE.md)
- 技能键位：[windows/docs/KEYBINDS.md](../windows/docs/KEYBINDS.md)
- 进程保存/恢复：[windows/docs/QUICK-RESUME.md](../windows/docs/QUICK-RESUME.md)

旧逐轮报告已并入以上文件，不再单独维护。
