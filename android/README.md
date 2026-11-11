# Android ARM64 兼容层

正式源码位于 `host/`、`app/`、`gpu/host/`，回归测试源码位于 `tests/`，构建和资源工具位于 `tools/`。该目录保留 Horizon 服务、guest 接入、Eden Vulkan、音频、内容、触控与物理手柄功能。

- [构建、资源及存档](docs/BUILD.md)
- [固定依赖与许可证](docs/DEPENDENCIES.md)
- [源码接口与约束](docs/ARCHITECTURE.md)
- [S2Arm 迁移与功耗优化路线、验收标准](docs/S2ARM-MIGRATION-ROADMAP.md)
- [当前验收与待完成项](docs/STATUS.md)
- [GPU 依赖补丁](gpu/patches/README.md)
- [跨平台逆向过程与踩坑](../docs/REVERSE-ENGINEERING.md)

输入放 `local/`，构建和测试输出统一放仓库根 `out/android/`。guest、签名和存档不要放入可清理的输出目录。

当前工作树包含尚未跟踪的 Android 源码、启动图标、测试和 Eden 补丁；单独克隆已有提交不会取得这些文件。整理或提交时先检查 `git status --short`，将需要保留的源码、资源和补丁一起纳入版本管理。

代码探索优先使用 Serena 符号概要、查询和引用。本地服务查询入口为 `tools/serena_query.py`，其服务地址由脚本配置；符号上下文不足时再定向检索和局部读取。
