# Android 第一章与中文音频交接

2026-10-19 续测：已迁移到 vivo X200 Pro。按屏幕比例修改 guest 原生分辨率，
并加入左侧安全区浮动摇杆；已补全本机 Mali 核心库，验证 app 内实际加载和宽屏标题渲染。
最新真机验证范围和驱动来源见 [X200 Pro 续测记录](X200PRO_20261019.md)。
下文的 SM-X700 数据为此前基线，不代表 X200 Pro 的玩法性能。

今日收尾：菜单场景/UI 比例常量已同步，并实现仅菜单背景的保守 FOV 候选。
**最终主菜单边缘的修复后截图未完成验收，用户已断开设备，今天停止实机操作。**
下次连接优先同场景复拍；虚拟键/画面按钮当前隐藏，按系统返回键可恢复。
实机原图与 4 张 X 宣传图已放入 [项目图集](../marketing/x200pro-20261019/)。

更新：2026-10-19，分支 `recovery/d3host-sources`。本文件为当前入口。
用户要求停止继续调试，更新文档并提交。首帧阶段记录见
[历史归档](HANDOFF_HISTORY_PRE_PLAYABLE_20261019.md)。

## 当前基线和限制

- 真机 `R52T90127WT` / Samsung SM-X700，Android 16，Adreno 730，2560×1600。
- `com.d3mobile.host.recovery`，系统 Vulkan、1.0×、write-watch 关闭。
- 最后验证 PID 5330 连续运行超过十分钟。第一章英雄 `Zogri`（男巫医），
  已验证触控移动、攻击、击杀、经验增长、存档恢复和 HOME→返回同一进程。
- 中文 DLC 部署、逐文件校验后，缺语音包提示消失；**用户确认“能听到中文对白”**。
- 系统 1.0× 早期玩法约 34–37fps；完整日志后段约 30–33fps，部分复杂/长时间片段约 21–28fps。
  下降原因尚未区分场景、温升和其他开销。1.5× 既有实测约 22–23fps。
- **完整第一章通关、持续稳定 60fps、跨设备兼容、OEM AI 插帧和超分均未验收。**
  标题/视频约 60fps 不能当玩法性能。
- 本次交接检查时目标平板已断开 ADB；未操作另一台已连接手机，未重新安装或清数据。
  PID/资源/存档均为最后一次验证记录，不代表当前在线。

截图、日志和身份见 [验收证据](evidence/20261019-handoff/README.md)。

## 构建身份

| 构建 | 本地 APK（相对仓库） | 验证范围 |
| --- | --- | --- |
| 真机基线 | `d3-android/build/apk-touch-audio/d3host-recovery-debug.apk` | 中文对白、第一章、存档、HOME 返回 |
| 当前源码交接包 | `d3-android/build/handoff-apk/d3host-recovery-debug.apk` | 重新编译、打包和签名成功；未安装 |
| 可选原神身份 | `d3-android/build/android-genshin/apk/d3host-recovery-debug.apk` | 已构建、未安装；早于末尾静态页 watch 变更 |

真机 APK SHA-256：
`fd88b9d2b7d778e6d3f64820c79fb3b278849bb0b9f024d9483c638520632cf3`。
host：`e5d995bc582826ea04cb6856f0ff92d31d0035e5eb40cfc1dfa01d5b667e7538`。

交接 APK SHA-256：
`63461ff8bb1a54ad91b1fa1080e92beebefea8106ddcaadd001afe6dc325f9b9`。
host：`df6f92bc04a3e2c8d55481d901adb508080e2de3f7a395a5a5ef3206babae203`。

交接构建包含末尾 AOC mount/unmount 日志节流及“连续 16 轮不变才 watch”实验源码，
这些末尾变更没有进入已验证的 PID 5330。实验仍默认关闭。

共同 guest：
`recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so`，
SHA-256 `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`。
完整元数据保存在 evidence 的 `device-tested-apk.json`、`handoff-apk.json` 和 `genshin-apk.json`。

## 本轮代码与定位

| 模块 | 入口与变化 |
| --- | --- |
| Android | `MainActivity.java`、`GameControlsView.java`、Manifest：横屏沉浸启动，左摇杆/右侧按钮区，多指绑定，全手柄键与物理输入，50ms 短按保持 |
| HID | `d3_host.c`、`d3_service.c`：memfd 双视图，guest 只读、服务端 RW，修复按 A 写只读映射闪退 |
| 音频 | `d3_audio.c`、`d3_audio_service.inc`、JNI：AAudio 48k PCM16 stereo，6ch downmix、tag/event、焦点/后台处理和断连重开 |
| 键盘/存档 | `d3_keyboard_service.inc`、`d3_save_ops.inc`：swkbd UTF16/UTF8、text-check、完成事件，真实建角及持久化 |
| DLC | `d3_content.h`、`d3_service.c::aoc_command`、host mount/path hooks、`hook_stub.S::d3_call_guest_one` |
| GPU | `gpu_host.cpp`、`renderer_bringup.cpp`、`emu_window_d3.*`：真实 GPFIFO、canonical mapping、精确页快照、三路扫描和 Surface 恢复 |
| 设置/打包 | `GraphicsSettings.java`、`graphics_config.*`、`build_adreno.py`、`build_android_profile.py`：倍率、驱动、匹配包名和 native 私有目录 |
| 同步 | `d3_sync.c`、host SVC、汇编：线程/TLS/x18，真实无限等待，ExitThread cleanup 完成通知 |
| 启动接口 | account cmd50 返回注册不可用；profile selector 0x10；offline web applet 0x1010 ExitRequested；friend 离线子集 |

这些是当前路径所需兼容子集，非完整 Horizon 实现。friend 10700 等仍有 unsupported。
不要用 `*_minimal.c`、`*_new.*`、`d3_table.c`、`jni_template.c` 代替正式源码。

## 中文语音与主资源

原设备 `CPKs` 只有 enUS 文件，AOC Count/List 为 0，也没有 DLC mount；
游戏中的中文选项不能代替资源安装。

- 原文件：`D:\workspace\Diablo\[20181102][XCI][Diablo III Eternal Collection][2.7.7.92380][1G+1U+4D][21.88 GB].xci`。
- 中文 title ID `01001b300b9bf00b`，DLC index **11**。
- NCA `c4cf91f251ed3209a50a5feb710282be.nca`，5,620,826,112 bytes。
- 本地 `reference/extract/voice_zh/romfs/`；14 个 `ztCN_*.cpk` 合计 5,609,750,528 bytes。
  包括一至五章、共用与过场语音；哈希见 evidence 的 `zh-voice-manifest.json`。
- 设备 `/data/local/tmp/d3romfs/AddOnContent/11/`，
  marker `.d3-content-complete` 内容 `01001b300b9bf00b` 加换行。
- 14 个文件本地与设备 SHA-256 一致后才写 marker。
  游戏实际打开 `aoc_11:/ztCN_Common.cpk`、CoreCommon、Act1 等。
  可选 `ztCN_ServerCommon.cpk` 打开失败未阻塞已验证对白。

`D3_CONTENT_ROOT` 默认 `/data/local/tmp/d3romfs`，与 app 私有 runtime 分开。
主游戏 `CPKs/` 必须保留正确更新版 CoreCommon/ServerCommon，换回旧版会复现 Particle 断言。
旧文件备份在 `recovery/resource-backup-20261019/`，不入 Git。

`d3_content.h` 仅识别有正确 marker 的安装；AOC Count/List 支持 offset/count 及真实输出 buffer，
Prepare 校验已安装。Mount cache-size hook `0x23be20` 返回 4096，mount `0x23c050` 注册只读挂载；
Unmount `0x204f80` 管理 DLC，其余通过保留原前 16 字节的 RX trampoline 调回 SDK。
`test_content` 覆盖读取、missing、只读、路径穿越和卸载；启动服务测试覆盖安装枚举。

提取/校验脚本已保留到 [tools/resource_recovery](tools/resource_recovery/README.md)。
**APK 不含主资源或约 5.2GiB 中文 DLC，换机必须另行部署。**

## GPU 与可选身份

画面设置提供 1.0×/1.5× 与 SAF ZIP 驱动导入，重启生效。
倍率作用于 Eden render targets，不是仅放大合成图；1.5× 目前性能不足。
libadrenotools 静态库和四个 hook so 已打包，自定义 OpenLibrary 与 driver 目录末尾斜线已接线。

- 系统 Vulkan：当前推荐基线。
- Turnip 26.0 R8：真实加载后 DEVICE_LOST。
- Turnip 24.3 R9v2：真实加载并运行标题/主菜单约 9 分钟；随后 account cmd50 abort。
  账号路径已另行修复，但该驱动未做同场景第一章对照，不能归因为 GPU 故障或宣称更快。
- 当前 native crash 回系统驱动范围较宽，非 GPU native crash 也可能误触发，诊断时注意。
- genshin profile 参考 Eden，包名 `com.miHoYo.Yuanshen` 且 native 私有路径匹配。
  已构建、未安装，OEM AI 功能无启用证据；安装前检查真正原神包及其数据。

## 写监控实验：默认关闭

默认精确页快照保证 CPU/GPU 缓存一致性，两个持久 worker 加提交线程三路扫描。
旧采样显示 memcmp/扫描为主要 CPU 开销；约 2–3 万页，是后续性能线索。

`cpu_write_watch.h` 对 host 管理的 RW guest heap/alias 页使用 mprotect、lock-free fault 状态，
识别 AArch64 ESR 写 fault，跟踪内核写入、权限变化和 uncache。
启用时 kernel interceptor 先于 ART prehandler 处理 guest TLS 下的写 fault，其余交回原信号链。

**只有 runtime 存在 `gpu-write-watch` marker 才启用**，JNI 与 signal installer 条件一致。
最后真机验证无此 marker，旧 `gpu-no-write-watch` 已无效。
全量 watch 集成曾在菜单处 abort：
`critical section ... wait failed: 0xe401`，owner `0x55`、tag `0x1`、
word `0x40000055`、owner-kind `0`。根因未解决。

最新“连续 16 轮不变才 watch、256 轮 audit”只通过独立测试；
本次源码已重建，未做真机集成验证。标题 60fps 不代表实验稳定，正常交接保持关闭。

## 存档与备份

设备根目录 `/data/user/0/com.d3mobile.host.recovery/files/runtime/saves/`，英雄文件：

```text
1-0000000000000000-4433484f53545531-4c4f43414c555345-0000000000000000-00000001/heroes/3ba77b620369e10e.dat
```

最后记录 639 bytes，持久化已验证。备份
`d3-android/build/touch-audio/saves-before-watch.tar`，28,672 bytes。
更新复用 `d3-android/build/apk-gpu-waitn/local-debug.keystore`，使用 `adb install -r`。
不要卸载、清数据或覆盖原 `com.d3mobile.host`，不要混用 genshin profile 的存档路径。

## 构建、测试和复测

仓库根 `D:\workspace\Diablo`，PowerShell，Python 3.12；
NDK `D:\workspace\Gdict\android_sdk\ndk\28.2.13676358`，minSdk 34、targetSdk 36。
需保留 Eden、third_party、Boost 1.86.0、guest 和签名文件。
版本、两处已有 Eden 修改和恢复方式见 [gpu/patches/README.md](gpu/patches/README.md)。
GPU PS1 硬编码本机路径，迁移先调整。新环境恢复依赖和补丁后先生成 shader headers：

```powershell
python -I d3-android/gpu/tools/gen_shaders.py
python -I d3-android/tools/build_android_profile.py --profile recovery --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --keystore d3-android/build/apk-gpu-waitn/local-debug.keystore
```

统一脚本输出 `build/android-recovery/`，不安装；可选 `--profile genshin`。
本次交接输出 `build/handoff-{host,apk}/`，等效分步命令：

```powershell
pwsh -File d3-android/gpu/build_gpu.ps1
python -I d3-android/tools/build_host.py --with-gpu --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --output-dir d3-android/build/handoff-host
python -I d3-android/tools/build_apk.py --host d3-android/build/handoff-host/libd3host.so --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --output-dir d3-android/build/handoff-apk --keystore d3-android/build/apk-gpu-waitn/local-debug.keystore --driver-hooks-dir d3-android/build/adrenotools/src/hook
python -I d3-android/tools/build_host.py --build-tests --build-gpu-tests --sandbox-root /data/local/tmp/d3-native-regression --output-dir d3-android/build/handoff-native
python -I -m unittest discover -s d3-android/tests -p 'test_*.py' -v
```

本次 GPU 353 个 translation units、严格 host 编译/链接、签名 APK、21 个 native 测试程序构建成功；
Python 两套工具回归通过。平板断开，**当前 21 套未整组重跑**。
此前 20 套真机结果见 evidence 的 `native-regression-previous.txt`。
之后内容挂载、账号和静态页 watch 测试分别通过，不混写为当前源码全部真机通过。

连接后，指定 `adb -s R52T90127WT` 将 `build/handoff-native/test_*` 推到
`/data/local/tmp/d3-native-regression/`，chmod 755 后**串行**运行，保留 exit code。
`test_guest_tls` 额外传该目录的 `guest.so`（保留 guest 的副本）。
测试沙箱与 app 存档分开，不要把 app 私有 runtime 当测试沙箱。

## 下一位的优先事项

1. 系统驱动、1.0×、write-watch 关闭，复测交接包冷启动、存档和中文对白。
2. 完成第一章连续任务及战斗验收；记录至少 15 分钟帧时间、温升和 unsupported 接口。
3. 同一存档比较系统与 Turnip 24.3 R9v2。写监控先解决 critical-section abort，再谈启用。
4. 补全技能/多指、物理手柄、蓝牙/耳机切换、Activity 销毁重建及多次后台恢复。
   当前旧 Surface 引用保留可能随重建增长，尚未测清。
5. 兼容 OEM 设备且无包冲突时验原神身份，分别证明 AI 开关和原生/显示帧率。

## Git 与迁移清单

源码、测试、构建工具、文档、依赖补丁及少量证据纳入本次 commit。
约 677MiB 自动生成日志/截图留在 `d3-android/gpu/probe/`，新阶段原始记录在 `build/touch-audio/`。
22 个一次性分析/文本替换草稿归档到 `tools/scratch/handoff-20261019/`；
其中空 `gen_guest_relocs.py` 不代表 guest 重建器已恢复。

Git 不含游戏数据、guest、APK、keys、私钥、存档、完整日志、依赖检出和生成文件。
迁移时另行保存 XCI、合法已有 keys、guest、keystore、RomFS/中文 DLC、存档备份、
Eden/third_party 和本地工具。当前依赖保留 guest，不能声称仅 Git 可完整重建。
没有配置 remote，本次只 commit、不 push。
