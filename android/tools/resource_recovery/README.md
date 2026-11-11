# 中文语音资源工具

所有命令从仓库根目录运行。原始 XCI 位于 `local/assets/game/`，密钥为 `local/keys/prod.keys`；它们及其他 `local/` 输入只读使用，不入 Git。

`inspect_xci.py` 默认要求游戏目录中恰好一份 XCI，也可用 `--source` 显式指定。索引写入 `out/android/resource-recovery/xci-index.json`。`--extract-voice` 只把中文语音 NCA 写入同一输出目录的 `voice-zh/`，已存在时拒绝覆盖；不会替换保留的语音 CPK。

```powershell
python android/tools/resource_recovery/inspect_xci.py --help
python android/tools/resource_recovery/inspect_xci.py --extract-voice
```

提取需要 Python `cryptography`。NCA header 使用 Nintendo XTS 的 big-endian sector tweak。解开 NCA 需已有本地 `nstool`；解包目标也应选 `out/`，验收后再由使用者明确部署资源。

当前完整更新资源位于 `local/assets/android/romfs/`；14 份中文语音 CPK 位于 `local/assets/android/voice-zh/`。本地校验无需设备：

```powershell
python android/tools/resource_recovery/verify_voice.py --local-only
```

需要部署到明确的 Android 设备时：

```powershell
$env:ANDROID_SERIAL = '目标设备串号'
adb get-state
adb shell mkdir -p /data/local/tmp/d3romfs/AddOnContent/11
adb push local/assets/android/voice-zh/. /data/local/tmp/d3romfs/AddOnContent/11/
python android/tools/resource_recovery/verify_voice.py --serial $env:ANDROID_SERIAL
```

校验器逐个比较设备 SHA-256，全部匹配后才写设备端安装 marker；`--local-only` 不连接 ADB，也不写 marker。两种模式的本地清单均写入 `out/android/resource-recovery/zh-voice-manifest.json`，可用 `--output` 改到其他生成输出位置。工具拒绝将输出写回 `local/`。不要提前写 marker。
