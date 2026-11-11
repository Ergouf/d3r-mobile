# Android 依赖与许可证

固定机器可读版本见 [dependencies-20261019.json](../../android/gpu/patches/dependencies-20261019.json)，应用方式见 [GPU 补丁说明](../../android/gpu/patches/README.md)。构建步骤见 [BUILD.md](BUILD.md)。


本项目在源码和构建期使用以下开源软件。表中的 commit 是当前验证过的固定版本；`android/gpu/patches/dependencies-20261019.json` 是机器可读版本。

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

