# 中文语音恢复脚本快照

保留本轮已用的脚本，非通用安装器。在仓库根运行，需要已有 XCI、prod.keys、
Python cryptography 和本地 nstool。资源与密钥不入 Git。

`inspect_xci.py` 使用根目录第一份 .xci 和 prod.keys，解密 NCA header 并生成索引；
Nintendo XTS sector tweak 使用 big endian。多份 XCI 时先明确脚本输入。
`--extract-voice` 提取中文 title ID `01001b300b9bf00b` 的 NCA。

```powershell
python d3-android/tools/resource_recovery/inspect_xci.py --extract-voice
& reference/tools/nstool/nstool.exe -k prod.keys --part0 reference/extract/voice_zh/romfs reference/extract/voice_zh/c4cf91f251ed3209a50a5feb710282be.nca
```

已部署设备无需重提取。换平板部署，先设置目标串号，再复制和逐文件校验：

```powershell
$env:ANDROID_SERIAL = 'R52T90127WT'
adb get-state
adb shell mkdir -p /data/local/tmp/d3romfs/AddOnContent/11
adb push reference/extract/voice_zh/romfs/. /data/local/tmp/d3romfs/AddOnContent/11/
python d3-android/tools/resource_recovery/verify_voice.py
```

校验器要求恰好 14 个 CPK，逐个比较本地与设备 SHA-256，全部匹配后写安装 marker。
仍输出到原 `d3-android/build/touch-audio/zh-voice-manifest.json`，运行前确保目录存在。
不要提前写 marker；替换已完成安装的资源时先移除 marker，再复制和校验。
已验证清单见 `../../evidence/20261019-handoff/zh-voice-manifest.json`。
