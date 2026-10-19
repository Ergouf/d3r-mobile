# 2026-10-19 验收证据

本目录只保存便于审阅的精简证据。完整原始 logcat、tombstone、截图和大体积日志留在本机
`d3-android/build/touch-audio/` 与 `d3-android/gpu/probe/`，不进入 Git。

## 当前已验证范围

- SM-X700 / Android 16 / Adreno 730，recovery 包、系统 Vulkan、1.0×、write-watch 关闭。
- 第一章触控移动、攻击、击杀、经验增长、存档恢复和 HOME 返回同一进程。
- 中文 DLC 挂载成功，缺语音包提示消失；用户确认能听到中文对白。
- 不是第一章通关，也不是稳定 60fps 验收。系统 1.0× 早期玩法约 34–37fps，
  完整日志后段约 21–33fps。标题/视频约 60fps 与玩法帧率分开。
- 本次交接检查时平板断开 ADB；本目录证明最后一次真机阶段，不代表当前在线。

## 文件

| 文件 | 内容 |
| --- | --- |
| `device-tested-apk.json` | 已在平板验证的 APK/host/guest 哈希和打包身份 |
| `handoff-apk.json` | 本次当前源码重建、签名成功的 APK；未安装 |
| `genshin-apk.json` | 可选 `com.miHoYo.Yuanshen` 包；已构建、未安装 |
| `gameplay.png` | 第一章道路、尸体血迹和经验条截图 |
| `resume.png` | HOME 后返回同一场景截图 |
| `game-audio-log.txt` | AAudio 播放、混合、DLC 打开、提交与呈现日志 |
| `voice-mount-excerpt.txt` | `aoc_11:` 中文资源实际打开记录 |
| `zh-voice-manifest.json` | 14 个中文 CPK 的大小和 SHA-256 |
| `native-regression-previous.txt` | 此前 20 套真机 native 测试结果；不是当前源码整组结果 |
| `write-watch-failure-excerpt.txt` | 写监控实验的 critical-section 失败摘要 |

真机 APK：`fd88b9d2b7d778e6d3f64820c79fb3b278849bb0b9f024d9483c638520632cf3`；
host：`e5d995bc582826ea04cb6856f0ff92d31d0035e5eb40cfc1dfa01d5b667e7538`。
交接 APK：`63461ff8bb1a54ad91b1fa1080e92beebefea8106ddcaadd001afe6dc325f9b9`；
host：`df6f92bc04a3e2c8d55481d901adb508080e2de3f7a395a5a5ef3206babae203`。
guest 均为 `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`。

## 本次源码构建验证

GPU 353 个 translation units 编译/归档、带 GPU 的 host 严格编译与链接、APK 签名和
21 个 native 测试程序构建成功。Python 工具回归 `Ran 20 tests ... OK`。
当前 21 套 native 未在设备整组重跑；此前 20 套结果见清单，不能与当前构建身份混写。
写监控最后两次 41-step 自动采集日志分别含 `critical section ... 0xe401` 和退出，
属于失败记录，不能作为通过证据。

构建、部署和待复测步骤见 [../HANDOFF_CURRENT.md](../HANDOFF_CURRENT.md)。
