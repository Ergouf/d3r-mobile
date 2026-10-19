# Diablo III Android 兼容层

通过专用 Horizon 兼容层、Eden Vulkan 渲染器和原生 Android APK 执行原始 ARM64 guest。

**交接状态：2026-10-19，分支 `recovery/d3host-sources`。** SM-X700 已进入第一章，
验证了触屏移动、攻击、击杀、经验增长、存档恢复及 HOME 返回。中文语音已补齐，
用户确认能听到中文对白。全屏启动、全部虚拟手柄键、GPU 驱动与 1.0×/1.5× 设置已接入。

**稳定 60fps 和第一章完整通关尚未验收。** 系统驱动 1.0× 早期玩法约 34–37fps，
长时间/复杂场景日志约 21–33fps；1.5× 既有实测约 22–23fps。
原神身份包已构建、未安装，OEM AI 插帧和超分没有启用证据。

- [当前交接、构建、资源和下一步](d3-android/HANDOFF_CURRENT.md)
- [目标与验收条件](d3-android/GOAL.md)
- [源码与工具入口](d3-android/README.md)
- [构建身份和验收证据](d3-android/evidence/20261019-handoff/README.md)
- [早期源码恢复记录](d3-android/RECOVERY.md)和[历史启动记录](HANDOFF.md)

游戏数据、guest 二进制、密钥、签名私钥、APK、第三方检出和完整日志留在本机。
仅克隆 Git 不能完整重建运行环境，迁移清单见当前交接。当前没有 Git remote，本地 commit 不构成异地备份。
