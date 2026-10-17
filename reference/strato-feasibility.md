# Strato/Skyline GPU 层移植可行性调研

日期：2026-10-18
背景：d3-android 自有 Horizon HLE host 已推进到 nvdrv/显示服务，但没有图形后端。
目标评估：把 Strato（Skyline 的活跃分支）的 GPU 层移植进本 host 需要多少工作。

## 1. GPU 层规模（GitHub API 实测）

| 目录 | 文件数 | 源码体积 |
|---|---|---|
| `skyline/gpu/`（顶层） | 19 | 250 KB |
| `skyline/gpu/texture/` | 8 | 196 KB |
| `skyline/gpu/interconnect/`（maxwell_3d / kepler_compute / conversion） | 10+ | 89 KB |
| `skyline/gpu/cache/` | 4 | 21 KB |
| `skyline/gpu/shaders/` | 2 | 23 KB |
| `skyline/soc/gm20b` + `soc/host1x` | 11 | 46 KB |
| `skyline/services/nvdrv` | 9 | 34 KB |
| **GPU 直接相关小计** | **~63** | **~660 KB** |

必须一起带入的支撑层：

| 目录 | 文件数 | 源码体积 |
|---|---|---|
| `skyline/kernel/` + `kernel/types/` | 25 | 238 KB |
| `skyline/common/` | 35 | 189 KB |

合计约 **1.05 MB C++ 源码（约 25–30k 行）**，不含第三方（Vulkan-Hpp、adrenotools）。

## 2. 接口边界（耦合点）

`gpu.h` 的构造签名即边界：

```cpp
class GPU {
    const DeviceState &state;   // ← 整个模拟器状态
    ...
};
```

`DeviceState` 聚合了 kernel（KMemory/KEvent/KThread）、services、soc、vfs、NCE。
GPU 层在以下位置反向依赖这些：

1. **内存访问**：`Buffer`/`Texture` 基于 `KMemory` + NCE 地址空间跟踪
2. **提交入口**：由 `services/nvdrv` 的 `/dev/nvhost-gpu` ioctl 触发
   `GPU::SubmitCommandBuffer`，再由 `soc/gm20b` 解析 Maxwell 命令流
3. **同步**：`kernel::KEvent` / fence cycle
4. **呈现**：`PresentationEngine` 需要真实的 `ANativeWindow`
5. **驱动注入**：`adrenotools`（可选）

## 3. 授权

Strato 为 **GPL-3.0**（Skyline 原为 MPL-2.0）。若把 Strato 代码链接进本 host，
整个 d3-android 需要以 GPL-3.0 发布。这是必须提前确认的法律约束。

## 4. 两条路线

### A. 移植 GPU 层（用户指定路线）

需要新建的适配层：
- 用本 host 的 guest 地址空间实现 Strato 的 `KMemory` 等价接口
- 在 `nvdrv` ioctl 处采集命令缓冲，喂给 `GPU::SubmitCommandBuffer`
- 把 `vi` 的假 native window 换成真实 `ANativeWindow`（Android Surface）
- 桩化 `DeviceState` 中 GPU 层实际用到的成员（需逐一甄别）

估算：**200–600 小时**（含调试着色器/纹理路径）。

### B. 直接用 Strato/Skyline 运行游戏

社区已有 **Skyline 运行《暗黑破坏神3：永恒珍藏版》** 的记录：

- bilibili：《安卓Skyline模拟器V40/M174版，NS《暗黑破坏神3：永恒珍藏版》试玩》
- Dzen：《Diablo 3 запустили на Android в 60 ФПС》

即「让暗黑3在安卓正常运行」这一目标**已有现成实现**，无需自研 GPU 后端。

## 5. 建议

1. 先用 Strato 在你平板上实测暗黑3（XCI + prod.keys 都已具备）
2. 若可运行 → 目标达成，本 host 可作为「自研兼容层」的长期实验并行推进
3. 若必须走自研路线 → 按 A 的适配层清单分阶段推进，优先打通
   「nvhost 提交 → gm20b 解析 → Vulkan 绘制」最小闭环

## 6. 本 host 侧的现状（供移植评估）

已完成：XCI 解包与符号恢复（25,142 符号）、guest 加载、SVC/IPC 翻译、
~30 条符号级 HLE、fs 完整读写、nvdrv 初始化、显示服务与 layer 生命周期、
真实 guest 线程 + 事件同步。

未完成：guest 在 `vi::GetNativeWindow` 之后仍会退出，尚未触达第一个 nvdrv ioctl。


---

# 附：eden-emu（Yuzu 系）量化对比

仓库：`eden-emulator/mirror`（镜像，GPL-3.0，C++，167 MB，2026-10-17 仍在更新，343 stars）

## 1. 图形相关源码规模

| 目录 | 文件数 | 源码体积 |
|---|---|---|
| `src/video_core/`（顶层，含 rasterizer 等大文件） | 48 | 1450 KB |
| `src/video_core/renderer_vulkan/` | 63 | 954 KB |
| `src/video_core/engines/`（Maxwell 各引擎） | 18 | 264 KB |
| `src/video_core/texture_cache/` | 25 | 268 KB |
| `src/video_core/host1x/` | 18 | 151 KB |
| `src/video_core/buffer_cache/` | 8 | 142 KB |
| `src/video_core/control/` | 7 | 13 KB |
| `src/shader_recompiler/`（着色器反编译 + SPIR-V） | 11(+3 目录) | 50 KB |
| **小计** | **~198** | **~3.3 MB** |
| `src/core/`（内存/内核/服务，必须一起带入） | 28(+10 目录) | 303 KB |

## 2. 与 Strato 的对比

| 维度 | Strato（Skyline 系） | Eden（Yuzu 系） |
|---|---|---|
| GPU 层源码 | ~660 KB | ~3.3 MB（约 5×） |
| 文件数 | ~63 | ~198 |
| 分层 | `gpu/` + `soc/gm20b`，与 `DeviceState` 强耦合 | `host1x`/`engines`/`renderer_vulkan` 分层清晰 |
| 着色器 | 依赖外部编译路径 | 自带成熟 `shader_recompiler`（反编译 IR → SPIR-V） |
| 授权 | GPL-3.0 | GPL-3.0 |
| 成熟度 | 活跃、体积小、Android 原生 | Yuzu 血统，后端更成熟、代码量大 |

## 3. 结论

- **代码量**：Strato 约小 5 倍，但耦合更深；Eden 大得多，但边界更干净
- **着色器**：Eden 自带完整 `shader_recompiler`，这是 Strato 侧需要额外补的部分，
  对「真正画出画面」而言 Eden 的完整度更高
- **移植落点**：两者都需要 `Core::System`/`DeviceState` 级别的宿主状态
  （内存访问、内核对象、服务），这是移植的主要工作量所在，而不是 GPU 代码本身

**建议**：若目标是「尽快出第一帧」，Eden 的 `shader_recompiler` + `renderer_vulkan`
组合更完整；若目标是「最小可维护的接入」，Strato 的体量更友好。两者都应先做
「最小闭环」验证（提交一个命令流 → 清屏 → 出图），再决定基线。


---

# Eden 接入方案（用户选定基线：尽快出第一帧）

## 1. 关键接缝（从源码头文件确认）

`src/video_core/gpu.h`：

```cpp
class GPU final {
    explicit GPU(Core::System& system, bool is_async, bool use_nvdec);
    void BindRenderer(std::unique_ptr<VideoCore::RendererBase> renderer);
    std::shared_ptr<Control::ChannelState> AllocateChannel();
    void InitChannel(Control::ChannelState&, u64 program_id);
    void BindChannel(s32 channel_id);
    void InitAddressSpace(Tegra::MemoryManager& memory_manager);
    void PushGPUEntries(s32 channel, Tegra::CommandList&& entries);   // ← 提交入口
    void RequestComposite(std::vector<Tegra::FramebufferConfig>&& layers,
                          std::vector<Service::Nvidia::NvFence>&& fences);  // ← 呈现出口
};
```

`src/video_core/memory_manager.h`：

```cpp
class MemoryManager final {
    explicit MemoryManager(Core::System& system_, u64 address_space_bits_ = 40, ...);
    [[nodiscard]] std::optional<DAddr> GpuToCpuAddress(GPUVAddr addr) const;
    u8* GetPointer(GPUVAddr addr);
    void ReadBlock(GPUVAddr, void* dest, std::size_t size, ...) const;
    void WriteBlock(GPUVAddr, const void* src, std::size_t size, ...);
};
```

## 2. 需要由我们提供的宿主层

| 需求 | 说明 |
|---|---|
| `Core::System` | Eden 的全局状态；GPU 层只用到其中一部分（内存、内核事件、服务） |
| `MaxwellDeviceMemoryManager` | GPU 页表背后的物理内存（对应我们的 guest RAM + nvmap 分配） |
| `Tegra::CommandList` 生产者 | 在 `nvdrv` 的 `/dev/nvhost-gpu` ioctl 处把命令缓冲封装成 CommandList |
| `RendererBase` 的呈现回调 | `RequestComposite` → 我们把它画到真实 `ANativeWindow` |

## 3. 里程碑阶梯

| 阶段 | 目标 | 验收 |
|---|---|---|
| **M0** | Eden `video_core` 在我们 APK 里能编译链接 | 构建通过 |
| **M1** | 内存管理器桩 + 一条清屏命令流 | 屏幕出现纯色 |
| **M2** | `nvdrv` ioctl → `PushGPUEntries` 打通 | guest 提交的命令被消费 |
| **M3** | 顶点/纹理路径 | 出现第一帧真实画面 |

## 4. 下一步（具体）

1. 本地浅克隆 Eden（GPL-3.0），对 `src/video_core` 做 `system\.` 依赖扫描，
   统计 `Core::System` 实际被用到的成员 —— 这个数字决定桩层规模
2. 按 M0 先把编译跑通（不接 guest），验证 ABI/工具链
3. M1 用最小命令流验证 Vulkan 后端

## 5. 授权提醒

Eden 为 **GPL-3.0-or-later**。把它的代码链接进 d3-android 会让整个项目受 GPL-3.0 约束。
若要避免，只能保持独立进程/服务边界（但那样共享内存和呈现都要走 IPC，性能与复杂度都会上升）。


---

# Eden 依赖扫描结果（本地浅克隆实测）

仓库已克隆到 `reference/eden`（git clone --depth 1，4595 文件）。

## 1. `src/video_core` 规模

```
354 个源文件，4.55 MB
```

## 2. 对 `Core::System` 的依赖（关键数字）

```
引用 system. 的文件：6 个（共 354 个）
distinct 成员：8 个
  GPU, Host1x, IsPoweredOn, GatherGPUDirtyMemory,
  CoreTiming, GetPerfStats, RegisterHostThread, DeviceMemory
```

**这个数字远比 Strato 乐观**：GPU 层只需要 8 个宿主成员，桩层可以做得很薄。

## 3. 对 `core/` 头文件的依赖

```
40 个文件 include 了 core/ 头，共 17 个不同头文件：
  16  core/core.h
  12  core/frontend/emu_window.h
   8  core/frontend/graphics_context.h
   4  core/frontend/framebuffer_layout.h
   4  core/core_timing.h
   2  core/memory.h
   2  core/hle/service/nvnflinger/pixel_format.h
   2  core/hle/service/nvdrv/nvdata.h
   1  core/device_memory_manager.h
   1  core/perf_stats.h
   1  core/guest_memory.h
   1  core/hle/kernel/k_page_table.h / k_process.h
   ...
```

## 4. 可直接复用的现成实现

| 组件 | 位置 | 用途 |
|---|---|---|
| Android `emu_window` | `src/android/app/src/main/jni/emu_window/` | 直接对接我们 Activity 的 Surface |
| Vulkan 后端 | `src/video_core/renderer_vulkan/`（含 `present/`） | 渲染 + 呈现 |
| 着色器反编译 | `src/shader_recompiler/` | Maxwell → SPIR-V |
| 命令流解析 | `src/video_core/host1x`、`engines`、`control` | 命令缓冲解码 |

## 5. M0 的准确定义

在 d3-android 里新建 `gpu/` 子树，包含：

1. `core/core.h` 的最小实现：一个 `Core::System` 类，只提供上述 8 个成员
2. 17 个 `core/` 头的桩（大部分是简单类型/接口）
3. `emu_window` 采用 Eden 的 Android 实现，绑定我们的 `Surface`
4. 用我们的 NDK（r28c）编译 `video_core` + `shader_recompiler` 静态库

验收：`libeden_gpu.a` 能在我们的 APK 里链接成功，且不依赖 Eden 的 Kotlin/Java 层。


---

# M0 进展：编译探针（Round 17）

## 1. 工具链验证通过

```
NDK r28c clang++ / --target=aarch64-linux-android34 / -std=c++20
#include "video_core/vulkan_common/vulkan.h" + "common/common_types.h"  → 编译通过
```

NDK 自带 Vulkan C 头（`vulkan.h`/`vulkan_core.h`）足够支撑 `vulkan_common`。

## 2. 已建立的兼容层（`d3-android/gpu/shim/`）

video_core 只用到 3 个 Boost 容器头，已用标准库替代：

| shim | 替代 |
|---|---|
| `boost/container/small_vector.hpp` | `std::vector` |
| `boost/container/static_vector.hpp` | `std::vector` |
| `boost/container/deque.hpp` | `std::deque` |
| `boost/unordered/unordered_flat_map.hpp` | `std::unordered_map` |

## 3. 新增依赖发现

编译 `video_core/memory_manager.cpp` 时依次暴露：

| 缺失 | 来源 | 处置 |
|---|---|---|
| `fmt/ranges.h` | `common/logging.h` | 已克隆 fmt（header-only） |
| `boost/unordered/...` | `common/container/unordered_map.h` | 已 shim |
| `std::stop_token` | `common/polyfill_thread.h` | 待处理（NDK libc++ 特性开关） |
| `boost/intrusive/rbtree.hpp` | `core/hle/kernel/k_auto_object.h` | **关键决策点** |

## 4. 关键决策：影子化 `core/` 头，而不是带 Eden 的内核

`boost/intrusive` 是通过 `core/core.h` → 内核头文件链被拉进来的。
但我们本来就要**自己写 `Core::System`**（只需 8 个成员）。

因此 M0 的正确做法不是补齐 Boost 全家桶，而是：

> 用我们自己的 `core/` 影子头（放在 include 路径最前面）
> 只声明 `video_core` 真正需要的 8 个成员和 17 个头，
> 完全绕开 Eden 的 `core/hle/kernel`、`services`、Boost.intrusive。

这样依赖面从「Eden 全内核 + Boost」收缩到「17 个薄头 + fmt + NDK Vulkan」。

## 5. 下一步

1. 逐个写 17 个影子头的最小实现（先满足声明，链接期再补实现）
2. 处理 `std::stop_token`（要么开 libc++ 特性，要么提供极简 polyfill）
3. 用 `-fsyntax-only` 逐个文件推进，直到 `video_core` 全量通过


## 6. M0 编译覆盖率（Round 18 实测）

`core/` 影子头建立后，代表性文件用 `-fsyntax-only` 试编译：

| 文件 | 结果 |
|---|---|
| `video_core/memory_manager.cpp` | ✅ 通过 |
| `video_core/control/channel_state.cpp` | ✅ 通过 |
| `video_core/buffer_cache/buffer_cache.cpp` | ✅ 通过 |
| `video_core/host1x/host1x.cpp` | ❌ 缺 `Core::System::DeviceMemory()` |
| `video_core/engines/maxwell_3d.cpp` | ❌ 缺 `boost/heap/fibonacci_heap.hpp` |
| `video_core/renderer_vulkan/renderer_vulkan.cpp` | ❌ 同上 |
| `video_core/texture_cache/texture_cache.cpp` | ❌ 缺 `boost/unordered/unordered_flat_set.hpp`（已补） |

已建立的桩：`core/core.h`、`core/hle/kernel/k_{page_table,process}.h`、
`video_core/host1x/ffmpeg.h`、`common/polyfill_thread.h`、`compat_thread.h`
（`std::jthread`/`std::stop_token` 替代）、Boost 容器 shim ×4。

**下一步**：补 `Core::DeviceMemoryManager` 与 `boost/heap/fibonacci_heap` 的兼容实现。


---

# M0 进展：Vulkan 路径全量语法通过（Round 19）

## 1. 结果

```
video_core（Vulkan 范围，排除 OpenGL / NVDEC / ReShade 后处理）119 个 .cpp
PASS 119/119  FAIL 0
NDK r28c clang++ --target=aarch64-linux-android34 -std=c++20 -fsyntax-only
```

探针脚本：[`d3-android/gpu/probe/coverage.ps1`](../d3-android/gpu/probe/coverage.ps1)，
逐文件 JSON 结果在 `coverage-video_core.json`（含首个错误），可直接按签名聚合。

## 2. 这一轮做对的三件事

### 2.1 不再手写 shim，直接吃 Eden 的 core 组件

| 组件 | 处置 |
|---|---|
| `core/device_memory_manager.h` + `.inc` | **使用 Eden 原版**（真实 GPU 页表、Asid、cached count） |
| `core/device_memory.h`、`common/host_memory.h` | 使用 Eden 原版（`Core::DeviceMemory` 的 ctor 由我们提供） |
| `common/settings.h` | 使用 Eden 原版（video_core 用到 65 个设置项，逐个桩不划算） |
| `common/polyfill_thread.h` | 使用 Eden 原版 |

仍然影子化的只剩 8 个薄头：`core/core.h`、`core/memory.h`、`core/core_timing.h`、
`core/perf_stats.h`、`core/hle/kernel/k_{page_table,process}.h`、
`video_core/host1x/ffmpeg.h`。

### 2.2 `std::jthread` / `std::stop_token` 不需要手写 polyfill

NDK r28c 的 libc++ 自带完整实现，只是默认关闭：

```
-D_LIBCPP_ENABLE_EXPERIMENTAL=1
```

打开后 `std::jthread`、`std::stop_source`、`std::stop_callback`、
`condition_variable_any::wait(lock, stop_token, pred)` 全部可用（均为 header-only，
不引入新的 .so 符号）。此前手写的 `compat_thread.h` 已删除——它把 stop 请求变成空操作，
会让关闭流程挂死。

### 2.3 第三方依赖用真实实现

| 依赖 | 位置 | 说明 |
|---|---|---|
| Boost 1.86 | `gpu/third_party/boost/boost_1_86_0` | `intrusive`、`icl`、`heap`、`pool`、`container`、`unordered` 全量真实头，删除全部 Boost shim |
| Vulkan-Headers | `gpu/third_party/Vulkan-Headers` | NDK 自带头缺 `VkPhysicalDeviceShaderQuadControlFeaturesKHR` 等新扩展 |
| VMA | `gpu/third_party/VMA` | `vk_mem_alloc.h` |
| Vulkan-Utility-Libraries | `gpu/third_party/Vulkan-Utility-Libraries` | `vulkan/vk_enum_string_helper.h` |
| fmt | `gpu/third_party/fmt` | header-only |

### 2.4 host shaders 生成

Eden 用 `glslangValidator --variable-name` 在 CMake 里生成 `*_spv.h`；NDK 的 `glslc`
是 shaderc 2022.3，没有该选项。改为自己生成：
[`d3-android/gpu/tools/gen_shaders.py`](../d3-android/gpu/tools/gen_shaders.py)
用 `glslc -DUseUniformBlock=1 --target-env=vulkan1.1` 编出 SPIR-V，再写成
`inline constexpr std::uint32_t <NAME>[]`（C 数组，因为 Eden 的 `ARRAY_TO_SPAN`
宏是 `std::span(a, sizeof(a)/sizeof(a[0]))`，`std::array` 无法这样 CTAD）。

```
generated 69/69 shader headers   （含 convert_msaa_* 的 sint/uint 变体）
```

## 3. 明确排除的范围（不影响第一帧）

| 排除 | 原因 |
|---|---|
| `renderer_opengl/**` | 只做 Vulkan 后端 |
| `host1x/codecs/**`、`host1x/ffmpeg.cpp`、`host1x/vic.cpp` | NVDEC 视频解码，暗黑3 不用 |
| `post_processing/**`、`present/post_process.cpp` | ReShade 后处理（`effect_module.hpp` 未随仓库分发） |
| 单独编译 `fidelityfx_fsr.frag` | 无 `#version` 的 include-only 片段，仅供 FSR 引用 |

## 4. 链接现状（M0 完成）

`libeden_gpu.a` 包含 **349 个 TU / 64.7 MB**：`video_core`、`shader_recompiler`、
sirit（`eden-emulator/sirit`）+ SPIRV-Headers、Eden 的 `core/device_memory*`、
`common/{assert,cityhash,dynamic_library,address_space,page_table,multi_level_page_table,
host_memory,settings,thread,adpf,error,logging,time_zone,string_util}`、
`common/fs/{file,fs_util,fs,fs_android,path_util}`、`common/android/{android_common,id_cache}`、
`core/frontend/{emu_window,framebuffer_layout}`、`externals/{bc_decoder,stb_dxt}`，
以及宿主适配层 `gpu/host/{gpu_host,vma_impl,nvdec_stub}.cpp`。

```
349/349 TU 编译通过
-Wl,--no-undefined 严格链接通过  →  libeden_gpu_probe.so  8.0 MB
```

视频解码（NVDEC）与 VIC 用 `gpu/host/nvdec_stub.cpp` 占位（暗黑3 不使用），
JNI 相关的 `InitJNI/NetworkShutdown/InitFFmpegOnLoad` 同样为零实现。

## 5. 下一步

1. ~~把 `libeden_gpu.a` 链进 `libd3host.so`~~ **已完成**（见下）
2. M1：真实 `ANativeWindow` + 一条清屏命令流（`GPU::PushGPUEntries` +
   `RequestComposite`）在真机出纯色
3. M2：`nvdrv` ioctl → `PushGPUEntries` 打通；M3：着色器/纹理路径出第一帧

## 6. 已链进 libd3host.so（真机验证）

`tools/build_host.py --with-gpu` 先用 clang 把 4 个 C 源编成 .o，再用 clang++
静态 libc++ 链上 `build/libeden_gpu.a`：

```
libd3host.so   9.42 MB   -Wl,--no-undefined 通过
```

`d3_jni.c` 在 `nativeStart` 里调用 GPU 侧的 `d3_gpu_probe_init()`
（`--with-gpu` 时是强引用，否则 weak），真机 `R52T90127WT` 日志：

```
I d3gpu: probe: device memory backing=0x6c80000000 virtual=0x6a7fe00000
```

即 C++ runtime、Eden 的 `Common::HostMemory`（4 GB 稀疏 backing + 8 GB 虚拟保留）
和 `Core::System`/`DeviceMemory` 都已在 APK 内正常工作，且 guest 启动流程无回归
（同一份日志里 D3Host 的 SVC/线程日志继续输出）。

注意：`-fvisibility=hidden` + `--exclude-libs,ALL` 让 C++ 符号保持库内私有，
只有 `d3_gpu_*` 入口是 default 可见性；weak 引用不会从静态库里拉成员，
所以 `--with-gpu` 必须走强引用宏 `D3_WITH_GPU`。

## 7. Vulkan 实例/设备真机通过（M1 第一步）

`gpu/host/vk_bringup.cpp` 用 Eden 的 `vulkan_common` 走完
`OpenLibrary → CreateInstance(WindowSystemType::Android) → EnumeratePhysicalDevices
→ CreateSurface → Vulkan::Device`，真机日志：

```
I d3gpu: vk: driver=Qualcomm devices=1 surface=0x0
```

即 Eden 的 Vulkan 初始化路径、Adreno 驱动探测、静态 libc++ 都在 APK 内正常。

两个已踩的坑：

1. `vkCreateAndroidSurfaceKHR` 会解引用窗口指针 —— 无窗口时必须真正 headless，
   不能把 `VK_NULL_HANDLE` 当窗口去建 surface（会 SIGSEGV 在 libvulkan 里）。
2. `vk::` 实际是 `Vulkan::vk`；`PhysicalDevice` 构造需要 `{VkPhysicalDevice, InstanceDispatch}`。

下一步 M1 收尾：Java 侧加 `SurfaceView`，JNI 传 `Surface` →
`ANativeWindow_fromSurface` → `d3_vk_probe(window)` → 建 swapchain →
清屏 + present，真机截屏验证纯色。
