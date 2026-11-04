# 项目目录约定

源码、长期文档、本地输入和可重建产物分开放置。当前状态见 [STATUS.md](STATUS.md)，具体构建步骤见 [Android](android/BUILD.md) 和 [Windows](windows/BUILD.md)。

| 目录 | 内容 | 维护规则 |
| --- | --- | --- |
| `d3-android/` | Android host、Java 外壳、GPU 适配、构建工具与回归测试源码 | 保留正式源码和未提交修改；不放测试日志、安装包或生成头 |
| `reference/ScarletNX-src/` | Windows 上游源码及本地 FSR 修改 | 保留独立工作树及补丁；构建输出放 `out/windows/` |
| `reference/eden/`、`d3-android/gpu/third_party/` | 固定版本第三方源码 | 按依赖清单与补丁恢复，不作为临时产物删除 |
| `reference/d3-symbols/` | SDK 符号查询资料 | 符号工具仍使用此目录 |
| `reference/legacy-recovery/` | 早期源码恢复快照 | 保留来源，不作为当前构建入口 |
| `tools/` | 跨项目维护工具、Windows 开发工具 | 新工具按用途归类，避免临时脚本散落根目录 |
| `docs/` | 当前状态、架构、构建、依赖和发行说明 | 同类信息合并维护；历史结论不冒充当前验收 |
| `assets/marketing/` | 保留的原图与宣传素材 | 按已有图集归类，测试截图进入 `out/` |
| `licenses/`、`patches/` | 额外许可与本地适配材料 | 与对应源码、构建入口一并维护 |
| `local/` | 游戏输入、guest、签名、存档、驱动 | 默认不入 Git；只读使用或明确备份，不能作为构建输出；发行归档已作为安装目录副本清理 |
| `out/android/` | profile、host、GPU、adrenotools、generated、probes、资源处理结果 | 可重建；原始签名、guest 和存档不得存于此处 |
| `out/windows/` | Windows 编译、测试、打包等输出 | 可重建；交付 ZIP 不长期保留，重打包时显式指定基线 |

Android 生成头位于 `out/android/generated/include/`，GPU 构建和 coverage 检查会自动补齐缺失或过期头文件。旧的 `d3-android/gpu/gen/`、`d3-android/build/` 和逐轮证据目录不再作为工具输入。

固定依赖清单与补丁文件名中的日期代表版本基线，不属于临时报告。不要仅按文件名包含日期就删除源码、补丁、存档或签名。

目录整理不改变原生业务实现，也不删除 `tests/` 下的回归源码。新增日志、截屏、测试副本和构建中间文件统一写入 `out/`，Python 缓存可通过 `-X pycache_prefix=out/android/python-cache` 放入同一输出树。

## Windows KBM 文档

- 当前交接：[windows/HANDOFF-20261104-CURRENT.md](windows/HANDOFF-20261104-CURRENT.md)
- 操作说明：[windows/KBM-INPUT-GUIDE.md](windows/KBM-INPUT-GUIDE.md)
- 技术证据与已知错误：[windows/KBM-RE-EVIDENCE.md](windows/KBM-RE-EVIDENCE.md)
- 技能键位：[windows/KEYBINDS.md](windows/KEYBINDS.md)
- 进程保存/恢复：[windows/QUICK-RESUME.md](windows/QUICK-RESUME.md)

旧逐轮报告已并入以上文件，不再单独维护。
