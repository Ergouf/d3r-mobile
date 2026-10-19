# d3r-mobile — Diablo III Android 兼容层

通过专用 Horizon 兼容层、Eden Vulkan 渲染器和原生 Android APK，在 ARM64 Android 设备上执行原始 Diablo III guest 二进制。

> 本项目仅用于兼容性研究、个人备份与互操作实验。仓库不包含游戏本体、固件、密钥、签名私钥、厂商 GPU 驱动或任何 Nintendo/Blizzard 的专有二进制。使用前请自行合法取得游戏与所需系统文件。

远程仓库：<https://github.com/Ergouf/d3r-mobile>

## 当前状态

2026-10-19，主分支 `main`（原 `master` 与 `recovery/d3host-sources` 已合并）。

- Samsung SM-X700（Adreno 730，Android 16）：已进入第一章，验证触屏移动、攻击、击杀、经验增长、存档恢复及 HOME 返回；中文语音已补齐并通过真机试听。
- vivo X200 Pro（Mali-G925，Android 16）：已接入原生宽屏、左侧安全区浮动摇杆、可隐藏/换位的虚拟手柄、Android 16 返回键设置入口；宽屏标题渲染通过，3D 场景、HUD 与完整玩法仍待验收。
- 性能：系统 Vulkan 1.0× 早期玩法约 34–37fps，长时间/复杂场景约 21–33fps；1.5× 约 22–23fps；X200 Pro 标题/视频原生约 44.8–45.1fps。**稳定 60fps、第一章完整通关、跨设备兼容均未验收。**
- 可选 `genshin` / `genshin-bilibili` 身份包已构建；OEM 游戏助手可识别并下发插帧配置，但实际插帧输出尚未验证。

### 插帧帧率

vivo X200 Pro 的 OEM 游戏助手为 `com.miHoYo.ys.bilibili` 下发了 `1:3:<pid>:45:90` 的插帧配置（`switchState=3`，显示模式 90Hz），即原生约 45fps → 插帧目标 **90fps**。这是当前配置的可达上限，不是已实测的稳定结果：

| 项目 | 结果 |
| --- | --- |
| 原生标题/视频帧率 | 44.77–45.09fps（8 组 5s 采样，PID 23462） |
| 插帧目标/显示上限 | **90fps（45→90）**，90Hz |
| 实际插帧输出 | 未验证（`interpolated_output_verified=false`） |
| MEMC 状态 | `isMEMCApp=0`、`mInitSuccess=0`、`MEMC_POST_PROCESSING_ENABLE_PROPERTY false`；`property.sys.game.memc.postprocessing.enable=0` |
| 设备 MEMC 能力 | `property.ro.vendor.mtk.gpu.game_memc=1` |
| 玩法帧率 | 未测量，不能把 90fps 当作已达成 |

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `d3-android/host/` | Horizon 兼容层：SVC/IPC、线程与 TLS、文件系统、HID、音频、内容挂载、nvdrv |
| `d3-android/gpu/` | Eden Vulkan GPU 桥接、shim、固定依赖补丁、shader 生成与探测工具 |
| `d3-android/app/` | Android Java 外壳：生命周期、全屏、触控/物理手柄、浮动摇杆、画面与驱动设置 |
| `d3-android/tests/` | native / Python / Java 回归测试 |
| `d3-android/tools/` | 构建、打包、符号解析、资源恢复与验证脚本 |
| `d3-android/evidence/` | 真机验收截图、日志与构建身份 |
| `recovery/` | 历史源码恢复快照与来源记录 |
| `reference/` | 分析脚本、符号资料、第三方检出与离线工具（第三方检出被忽略） |
| `research/` | 架构调研与方案记录 |

## 开源依赖

本项目在源码和构建期使用以下开源软件。表中的 commit 是当前验证过的固定版本；`d3-android/gpu/patches/dependencies-20261019.json` 是机器可读版本。

### 运行时 / 链接依赖

| 依赖 | 固定版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| [Eden](https://github.com/eden-emulator/mirror) | `e0d47f2790e3f758fa2188926a0bb2f56af6b310` | GPL-3.0 | Vulkan 渲染器、video_core、shader recompiler、common/fs 等 GPU 子树 |
| [Sirit](https://github.com/eden-emulator/sirit) | `7eb23c168629347f6de93487a309a93de2415bb2` | AGPL-3.0 | shader_recompiler 的 SPIR-V 构建器 |
| [libadrenotools](https://github.com/bylaws/libadrenotools)（含 linkernsbypass） | `8fae8ce254dfc1344527e05301e43f37dea2df80` | BSD-2-Clause | 自定义 Vulkan 驱动加载、hook 与 linker namespace 绕过 |
| [fmt](https://github.com/fmtlib/fmt) | `18164eaf8bd04879a058b8a6f14d8386d13e1582` | MIT | Eden/宿主格式化（header-only） |
| [Boost](https://github.com/boostorg/boost) | 1.86.0 | BSL-1.0 | Eden 使用的 header-only 容器与工具 |
| [Vulkan-Headers](https://github.com/KhronosGroup/Vulkan-Headers) | `acbb9391c0a597272800cd3f4363661c00a27c77` | Apache-2.0 OR MIT | Vulkan API 头文件 |
| [Vulkan-Utility-Libraries](https://github.com/KhronosGroup/Vulkan-Utility-Libraries) | `90738f6edfa19561a978fc5f97543ba37075ba9d` | Apache-2.0 | Vulkan 辅助库 |
| [VulkanMemoryAllocator](https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator) | `bfb2ca99e1e7e9684dc06546b552ee3eff4b10aa` | MIT | Vulkan 显存分配 |
| [SPIRV-Headers](https://github.com/KhronosGroup/SPIRV-Headers) | `86f980c731e62ae4eaf383d320449d71687936bf` | MIT（Khronos） | SPIR-V 枚举与头文件 |
| [bc_decoder](https://github.com/skyline-emu/skyline)（Eden externals） | 随 Eden 基线 | MPL-2.0 | BCn 纹理解码 |
| [stb_dxt](https://github.com/nothings/stb)（Eden externals） | v1.12，随 Eden 基线 | MIT | DXT 纹理压缩 |
| [FidelityFX-FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR)（Eden externals） | 随 Eden 基线 | MIT | FSR 着色器 |

说明：

- Eden 与 Sirit 为 copyleft 组件。当前 APK 会静态链接 Eden GPU 子树和 Sirit；分发 APK 时必须同时满足 GPL-3.0 / AGPL-3.0 的源码提供与许可证保留要求。
- `FFmpeg` 在 Eden 中用于 NVDEC 视频解码，但本项目的首帧/玩法路径显式使用 `nvdec_stub.cpp`，**当前构建不编译 FFmpeg**，因此未列入运行时依赖。
- 系统 `libvulkan.so`、Mali/Adreno 厂商驱动、Android 平台库（AAudio、ANativeWindow 等）由设备提供，不属于本仓库。

### 构建工具链

| 组件 | 版本/要求 | 许可证 | 用途 |
| --- | --- | --- | --- |
| Android SDK Platform | `android-36` | Apache-2.0 | 编译/链接 Android 应用 |
| Android SDK Build-Tools | `36.0.0` | Apache-2.0 | `aapt2`、`d8`、`zipalign`、`apksigner` |
| Android NDK | `28.2.13676358` | Apache-2.0（LLVM 组件为 Apache-2.0 with LLVM exception） | clang、lld、libc++、llvm-ar/nm/readelf |
| OpenJDK | 17 | GPL-2.0 with Classpath Exception | `javac`、`java`、`keytool` |
| CMake | `3.22.1`（SDK 随附） | BSD-3-Clause | 构建 libadrenotools |
| Ninja | SDK 随附 | Apache-2.0 | CMake 生成器 |
| glslc / Shaderc | NDK shader-tools 随附 | Apache-2.0 | GLSL → SPIR-V |
| Python | 3.12 | PSF-2.0 | 构建与资源脚本 |
| PowerShell | 7+ | MIT | `build_gpu.ps1` 与打包脚本 |
| Git | 2.x | GPL-2.0 | 获取固定 revision 依赖 |

### 离线资源/分析工具

| 工具 | 许可证 | 用途 |
| --- | --- | --- |
| [hactool](https://github.com/SciresM/hactool) | ISC | 读取 XCI/NCA 等容器（仅本地资源准备） |
| [nstool](https://github.com/jakcron/nstool) | MIT | 检查 NSO/NCA 等文件（仅本地资源准备） |

这些工具的可执行文件位于 `reference/tools/`，只用于本地资源检查；仓库不包含它们处理所需的游戏数据或密钥。

## 构建

### 1. 准备工具链

- 安装 Android SDK Platform 36、Build-Tools 36.0.0、NDK 28.2.13676358、JDK 17、Python 3.12、PowerShell 7、CMake/Ninja。
- 当前脚本含有本机路径默认值（`D:\workspace\Diablo`、`D:\workspace\Gdict\android_sdk`）。迁移到新机器时，通过 `--sdk` / `--ndk` 传参或修改脚本默认值。

### 2. 恢复固定 revision 的依赖

`reference/eden` 与 `d3-android/gpu/third_party/*` 被 `.gitignore` 排除，克隆主仓库不会带上它们。按 `d3-android/gpu/patches/dependencies-20261019.json` 恢复：

```powershell
git clone https://github.com/eden-emulator/mirror.git reference/eden
git -C reference/eden checkout e0d47f2790e3f758fa2188926a0bb2f56af6b310
git -C reference/eden submodule update --init --recursive
git -C reference/eden apply --check ../../d3-android/gpu/patches/eden-local-20261019.patch
git -C reference/eden apply ../../d3-android/gpu/patches/eden-local-20261019.patch
```

其余依赖（fmt、libadrenotools、sirit、SPIRV-Headers、VMA、Vulkan-Headers、Vulkan-Utility-Libraries）按 JSON 中的 `origin` + `revision` 检出到对应 `third_party` 目录；Boost 使用 1.86.0 本地 archive。`build_adreno.py` 会校验 libadrenotools revision，并幂等应用 `adrenotools-mali-isolation.patch`。

### 3. 生成 shader 头文件

```powershell
python -I d3-android/gpu/tools/gen_shaders.py
```

脚本默认使用 NDK `shader-tools/windows-x86_64/glslc.exe`；路径不同时请修改脚本中的 `GLSLC`。

### 4. 构建 GPU、host 与 APK

一键 profile（推荐）：

```powershell
python -I d3-android/tools/build_android_profile.py --profile recovery --guest <libd3guest.so> --keystore <local-debug.keystore>
```

分步：

```powershell
python -I d3-android/tools/build_adreno.py --sdk <sdk> --ndk <ndk>
pwsh -File d3-android/gpu/build_gpu.ps1
python -I d3-android/tools/build_host.py --with-gpu --ndk <ndk>
python -I d3-android/tools/build_apk.py --host <libd3host.so> --guest <libd3guest.so> --keystore <keystore>
```

`--profile genshin` / `genshin-bilibili` 只改变包名与 native 私有路径；不会安装或修改真实原神数据。

### 5. 测试

```powershell
bash d3-android/build.sh --build-tests
```

覆盖 native host、HID、音频、同步、内容挂载、显示 patch 等；Java 测试位于 `d3-android/tests/java/`，Python 测试位于 `d3-android/tests/`。具体验收状态见 [VERIFICATION.md](d3-android/VERIFICATION.md) 和 [当前交接](d3-android/HANDOFF_CURRENT.md)。

## 许可证与合规

- 本仓库原创部分以 **GNU AGPL-3.0** 发布，完整文本见 [LICENSE](LICENSE)。
- 由于静态链接 Eden（GPL-3.0）与 Sirit（AGPL-3.0），编译产物整体按 AGPL-3.0 分发；第三方组件仍保留各自版权与许可证。
- 分发二进制时必须保留版权声明与许可证文本，并按 AGPL-3.0 / GPL-3.0 提供对应源码。
- 仓库不包含 Diablo III 游戏数据、Nintendo Switch 固件、`prod.keys`、签名私钥、厂商 GPU 驱动或第三方检出。上述内容即使存在于本地工作区，也不属于本仓库或 AGPL 授权范围。
- 本项目与 Blizzard Entertainment、Nintendo 无隶属关系；请仅对你合法拥有的游戏与系统文件使用。

## 相关文档

- [当前交接、构建、资源和下一步](d3-android/HANDOFF_CURRENT.md)
- [目标与验收条件](d3-android/GOAL.md)
- [源码与工具入口](d3-android/README.md)
- [构建身份和验收证据](d3-android/evidence/20261019-handoff/README.md)
- [X200 Pro 续测记录](d3-android/X200PRO_20261019.md)
- [GPU 依赖与补丁](d3-android/gpu/patches/README.md)
- [早期源码恢复记录](d3-android/RECOVERY.md)和[历史启动记录](HANDOFF.md)
