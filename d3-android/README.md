# Diablo III Android 兼容层

2026-10-19：SM-X700 已进入第一章，触屏移动、战斗、存档恢复和中文对白已验证，
全屏及全部虚拟手柄键已接入。系统驱动 1.0× 早期约 34–37fps，长时间/复杂场景约 21–33fps；
稳定 60fps 和第一章完整通关仍待完成。

先读 [当前交接](HANDOFF_CURRENT.md)、[目标](GOAL.md)和[验收证据](evidence/20261019-handoff/README.md)。
vivo X200 Pro 原生宽屏、左侧安全区浮动摇杆和 Mali 补全包见 [续测记录](X200PRO_20261019.md)。
补全包使用本机 r49p1 实现，不是新版驱动；已验证 app 内实际加载及宽屏标题渲染，
完整玩法、HUD 和长时稳定性仍待验收。
旧首帧、nnMain 和 time 服务记录仅对应历史阶段。

## 正式源码

- `host/d3_host.c`、`d3_service.c`、`d3_sync.c`、`hook_stub.S`：guest、SVC/IPC、线程和文件系统。
- `host/d3_nvdrv.c`、`gpu/host/`：GPU 服务、Eden Vulkan 和呈现。
- `host/d3_audio.c`、`d3_audio_service.inc`：PCM 混音与音频服务。
- `host/d3_content.h`：完整安装的 AOC 内容识别。
- `d3_keyboard_service.inc`、`d3_save_ops.inc`、`d3_friend_service.inc`：键盘、存档和离线接口。
- `host/d3_jni.c`、`app/src/com/d3mobile/host/`：Android 生命周期、全屏输入和设置。
- `tests/`、`tools/`：native/Python 回归、构建、打包和资源恢复工具。

`*_minimal.c`、`*_new.*`、`d3_table.c` 和 `jni_template.c` 为旧漂移产物，不参与正式构建。

## 构建入口

在仓库根、PowerShell 运行：

```powershell
python -I d3-android/tools/build_android_profile.py --profile recovery --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --keystore d3-android/build/apk-gpu-waitn/local-debug.keystore
```

脚本构建 adrenotools、GPU、host 和 APK，不安装。NDK 28.2.13676358、第三方依赖、
生成 shader headers、guest 和签名文件须已准备；步骤见当前交接和 [依赖补丁](gpu/patches/README.md)。
`--profile genshin` 使用 `com.miHoYo.Yuanshen`；`--profile genshin-bilibili` 使用
`com.miHoYo.ys.bilibili`，后者已在 X200 Pro 安装并被识别为游戏，AI 插帧仍未验收。
设备已有真实原神时保留其包和数据。正常基线为系统 Vulkan、1.0×、write-watch 关闭。
APK 和 Git 不含主游戏及约 5.2GiB 中文资源。

## 代码探索

优先 Serena 符号概要、符号查询和引用。例如：

```powershell
python d3-android/tools/serena_query.py get_symbols_overview '{"relative_path":"d3-android/host/d3_host.c","depth":1}'
```

需另行运行本地服务 `http://127.0.0.1:9144/mcp`。当前启用 C/C++；
Python、Java 或 .inc 无法提供符号上下文时，用 rg 和局部读取。
