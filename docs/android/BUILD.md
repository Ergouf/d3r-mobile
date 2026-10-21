# Android 构建与运行

在项目根目录运行命令。当前验收范围见 [状态](../STATUS.md)，固定依赖见 [依赖说明](DEPENDENCIES.md)。

## 输入与工具链

- Android SDK Platform 36、Build-Tools 36.0.0、NDK `28.2.13676358`、OpenJDK 17、Python 3.12、PowerShell 7、Git、CMake/Ninja。
- 当前机器 SDK 为 `D:\workspace\Gdict\android_sdk`。脚本仍有本机默认路径，迁移时使用 `--sdk`、`--ndk` 参数或调整脚本路径。
- 保留原始 `libd3guest.so`、与目标安装身份匹配的 keystore、游戏资源和存档。这些输入放在本地专用目录，不能依赖临时构建目录，也不纳入 Git。
- 已验证 guest SHA-256：`dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`。

本地输入位置：

| 路径 | 内容 |
| --- | --- |
| `local/android/libd3guest.so` | 保留的原始 guest |
| `local/android/signing/validation-debug.keystore` | 现存 validation 调试签名，不能代替原 genshin 包签名 |
| `local/android/packages/validation/` | 独立验证 APK |
| `local/android/packages/installed-baseline/` | 原安装基线 APK，身份及签名与 validation 不同 |
| `local/android/drivers/driver-copy.tar` | Android 驱动相关本地材料 |
| `local/assets/android/romfs/` | 匹配更新的合并主资源 |
| `local/assets/android/voice-zh/` | 14 个中文 CPK |
| `local/saves/android/` | `before-test.tar` 与 `after-baseline.tar` 两份 Android 存档备份 |

原始 XCI、提取 ExeFS、密钥分别集中在 `local/assets/game/`、`local/assets/exefs/`、`local/assets/exefs_update/` 和 `local/keys/`；固件、厂商驱动放 `local/firmware/`、`local/drivers/`。它们不进入源码 Git。

## 依赖与着色器

按 [固定依赖清单](../../d3-android/gpu/patches/dependencies-20261019.json) 恢复 `reference/eden` 与 `d3-android/gpu/third_party/`。克隆本仓库不会自动取得这些目录。保留 Boost 1.86.0 本地 archive，以及清单要求的子模块。

Eden 基线检出后应用 [本地适配补丁](../../d3-android/gpu/patches/eden-local-20261019.patch)。已有补丁的工作树不要重复应用；先检查状态。libadrenotools 的 Mali 隔离补丁由构建器校验并幂等应用，详见 [GPU 补丁说明](../../d3-android/gpu/patches/README.md)。

```powershell
python -I d3-android/gpu/tools/gen_shaders.py
```

生成器使用 NDK shader-tools 的 `glslc.exe`，输出到 `out/android/generated/include/`。GPU 构建和 coverage 检查会自动调用 `--ensure`，补齐缺失或过期头文件；不需要恢复旧 `d3-android/gpu/gen/`。脚本中的工具链路径须与本机安装一致。

## 构建 APK

推荐使用统一 profile 构建器，显式传入保留的 guest 和签名文件：

```powershell
python -I d3-android/tools/build_android_profile.py --profile validation --guest local/android/libd3guest.so --keystore local/android/signing/validation-debug.keystore
```

它构建 adrenotools、GPU、host 和 APK，不安装。产物统一放在 `out/android/`：profile 包放在 `{profile}/host` 与 `{profile}/apk`，独立 host 放 `host/`，GPU 放 `gpu/`，驱动工具放 `adrenotools/`，诊断输出放 `probes/`。这些目录均为可重建产物。

可选 `--profile genshin`、`genshin-bilibili` 分别使用 `com.miHoYo.Yuanshen`、`com.miHoYo.ys.bilibili`。身份选项不等于 OEM 插帧已经工作。不要覆盖设备上的真实原神或使用不匹配签名更新既有包。

分步构建：

```powershell
python -I d3-android/tools/build_adreno.py --sdk <sdk> --ndk <ndk>
pwsh -File d3-android/gpu/build_gpu.ps1
python -I d3-android/tools/build_host.py --with-gpu --ndk <ndk> --output-dir out/android/host
python -I d3-android/tools/build_apk.py --host out/android/host/libd3host.so --guest local/android/libd3guest.so --keystore <匹配目标身份的keystore> --output-dir out/android/recovery/apk
```

## 内容与存档

APK 不包含主游戏或约 5.2GiB 中文 DLC。主资源默认位于设备 `/data/local/tmp/d3romfs`；资源检查工具见 [resource_recovery](../../d3-android/tools/resource_recovery/README.md)。

中文 title ID 为 `01001b300b9bf00b`，DLC index 为 `11`。完整部署位置为 `/data/local/tmp/d3romfs/AddOnContent/11/`，14 个 `ztCN_*.cpk` 总计 5,609,750,528 bytes。逐文件校验后写 `.d3-content-complete`，内容为 title ID 加换行；不完整安装不得写完成标记。主资源须使用匹配更新版本的 CoreCommon/ServerCommon。

应用存档位于相应包的 `files/runtime/saves/`。备份整个存档目录；复用原签名执行更新，保留应用数据。不同 profile 的私有路径和存档互相独立。

## 回归与实机检查

```powershell
python -I -m unittest discover -s d3-android/tests -p 'test_*.py' -v
bash d3-android/build.sh --build-tests
```

Java 测试在 `d3-android/tests/java/`。native 测试构建成功不等于已经在 ARM64 设备执行；指定目标设备串行运行并记录退出码。正常基线使用系统 Vulkan、1.0×、write-watch 关闭。

`rebuild_and_probe.ps1` 默认使用隔离的 validation 身份，以及保留的 validation 签名；可显式传入 `-Profile`、`-Package`、`-Guest`、`-Keystore`、`-Python`。它检查输入后才构建，安装只使用 `adb install -r`，probe 传入 `-Keep` 保留应用数据。默认签名不能用于覆盖原 genshin 身份。

`gpu-write-watch` 是未完成实机验收的实验开关，不能作为默认优化。安装前确认设备序列号、包名和签名，避免卸载、清数据或混用 profile 存档。
