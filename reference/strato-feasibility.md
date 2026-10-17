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

## 8. M1 达成：交换链 + 纯色上屏（真机截屏验证）

`MainActivity` 增加 `SurfaceView`，`surfaceCreated` 调
`nativePresent(holder.getSurface())` → `ANativeWindow_fromSurface` →
`gpu/host/vk_clear.cpp: d3_vk_clear(window)`，用原始 Vulkan 完成
「建交换链 → 取图 → 清成固定颜色 → present」。真机日志：

```
I d3gpu: vk-clear: swapchain 2484x475 format=37 images=4
I d3gpu: vk-clear: presented image 0 result=0
```

截屏取样（2560x1600，SurfaceView 中心 x=1280,y=512）：**(40, 88, 209)**，
与清屏色 `(0.05, 0.35, 0.85)` 一致。证据图：
[`d3-android/gpu/probe/m1-clear-2026-10-18.png`](../d3-android/gpu/probe/m1-clear-2026-10-18.png)

这一轮又踩了两个坑：

1. **`System.loadLibrary` 必须在静态初始化里**：`SurfaceView` 的
   `surfaceCreated` 比“点击启动”更早触发，否则 `nativePresent` 抛
   `UnsatisfiedLinkError`。
2. **`vk::SurfaceKHR` 是拥有型包装**：`*Vulkan::CreateSurface(...)` 取原始句柄后
   临时对象立刻析构并销毁 surface，后续 `vkGetPhysicalDeviceSurfaceCapabilitiesKHR`
   在 libvulkan 里 SIGSEGV。必须让 owner 活到使用结束。

## 9. 下一步（M2）

1. 用 Eden 的 `RendererVulkan`（而不是手写清屏）接 `EmuWindow` 子类，把
   `SurfaceView` 的 `ANativeWindow` 变成真正的 `render_surface`
2. `nvdrv` 的 `/dev/nvhost-gpu` ioctl → `GPU::PushGPUEntries` 打通
3. 把 guest 的 framebuffer 清除/呈现命令翻译成第一次真实绘制

## 10. Eden 渲染器真机初始化成功（M2 起点）

`gpu/host/emu_window_d3.{h,cpp}` + `gpu/host/renderer_bringup.cpp`：
用 `D3::EmuWindowD3`（`window_info.type = Android`、`render_surface = ANativeWindow`）
与 `GraphicsContextD3`（返回同一份 libvulkan）实例化 Eden 的
`Vulkan::RendererVulkan`，再 `gpu.BindRenderer(...)`。真机日志：

```
I d3gpu: renderer: Vulkan::RendererVulkan ready (vendor=Qualcomm)
```

`libd3host.so` 现在 15.3 MB（VMA / present manager / scheduler / state tracker
全部在内），进程存活、SurfaceView 仍显示清屏色。

## 11. M2 待办

1. 用真实 `FramebufferConfig` 调 `GPU::RequestComposite`，让 present manager 接管呈现
2. `nvdrv` ioctl（`/dev/nvhost-gpu` NvGpuAS / NvGpuChannel）→ `GPU::AllocateChannel` /
   `InitChannel` / `PushGPUEntries`
3. guest 的 Maxwell 命令流进入 `Tegra::GPU`，M3 出第一帧

## 12. M2 探查：`InitChannel` 需要先建地址空间（未完成）

`d3_gpu_channel_test()` 尝试 `AllocateChannel → InitChannel`，真机崩溃点：

```
#00 Tegra::MemoryManager::BindRasterizer(RasterizerInterface*)+0
#01 Tegra::Control::ChannelState::BindRasterizer(RasterizerInterface*)+48
#02 Tegra::GPU::InitChannel(ChannelState&, u64)+72
```

即通道初始化会把 rasterizer 绑到该通道的 `Tegra::MemoryManager`，而这个内存管理器
必须先由 nvdrv 的 NvGpuAS 分配路径初始化（`GPU::InitAddressSpace` 只是其中一步，
之后还需要 `MemoryManager::Init` 建立页表）。

补上 `InitAddressSpace(host1x.gmmu_manager)` 后仍崩溃，说明还缺页表初始化；当前
设备包已回退到不含该调用的稳定版本（进程存活、渲染器就绪、清屏色在屏）。

下一轮 M2 的正确顺序：
1. 在 host 侧建模 nvdrv 的 `NvGpuAS`：分配时调用 `MemoryManager::Init(page_bits, as_bits)`，
   建立页表并 `BindRasterizer`
2. 再 `GPU::AllocateChannel` / `InitChannel` / `BindChannel`
3. 最后把 `/dev/nvhost-gpu` 的 pushbuffer ioctl 喂给 `GPU::PushGPUEntries`

## 13. M2 进展：通道生命周期真机打通

按 nvdrv 的真实顺序补齐后，`d3_gpu_channel_test()` 在真机通过：

```cpp
g_address_space = std::make_unique<Tegra::MemoryManager>(*g_system);   // 40 bit AS
g_system->GPU().InitAddressSpace(*g_address_space);
auto channel = g_system->GPU().AllocateChannel();
channel->memory_manager = g_address_space.get();   // nvhost_as_gpu::BindChannel
g_system->GPU().InitChannel(*channel, 0);
```

```
I d3gpu: renderer: Vulkan::RendererVulkan ready (vendor=Qualcomm)
I d3gpu: channel: allocated and initialised (0xb4...)
```

之前的崩溃就是 `ChannelState::memory_manager` 为空指针（`BindRasterizer+0`）。

## 14. M2 剩余

1. `GPU::PushGPUEntries(channel_id, CommandList&&)`：需要一个真实的
   `Tegra::CommandList`（Maxwell 命令头），先把空/最小命令流送进去
2. 把 host 现有 `nvdrv` ioctl 处理接到这套对象上（`/dev/nvhost-gpu` 的
   NvGpuChannel / NvGpuAS fd 与 `channel->bind_id` 对应）
3. 再谈 `RequestComposite` 真实 framebuffer（需要 GMMU Map + guest RAM）

## 15. M2 探查：空 `PushGPUEntries` 会卡住

在通道初始化成功后追加：

```cpp
g_system->GPU().PushGPUEntries(channel->bind_id, Tegra::CommandList{});
```

真机上调用不返回（后续日志不再输出，进程仍存活、无 tombstone），说明空命令列表
让 GPU 线程进入等待、`SubmitList` 不返回。结论：**不能靠空列表验证提交路径**，
必须从 nvdrv 的 pushbuffer 路径带真实命令进来。

当前设备包已回退到「渲染器 + 通道初始化」的稳定版本（清屏色在屏、进程存活）。

## 16. M2 接口层：C ↔ C++ 桥打通

新增 [`gpu/host/gpu_bridge.h`](../d3-android/gpu/host/gpu_bridge.h)（纯 C ABI）：

```c
int d3_gpu_bridge_start(void* native_window);  /* renderer + AS + channel */
int d3_gpu_bridge_channel_id(void);            /* bind_id 或 -1 */
```

host 侧 `d3_jni.c` 直接调用并打印，真机日志：

```
I d3gpu: renderer: Vulkan::RendererVulkan ready (vendor=Qualcomm)
I d3gpu: channel: allocated and initialised (0xb4...)
I d3host: gpu bridge ready, channel=1
```

也就是 **C 侧（nvdrv 服务的宿主）已经能驱动 C++ 的 Eden GPU 栈**，这是 M2 把
`/dev/nvhost-gpu` ioctl 接进来的接缝。

注意：非 `--with-gpu` 构建里桥函数是 weak，调用点必须走 `D3_GPU_CHANNEL_ID()`
这类宏，不能直接调用弱符号（否则空指针调用）。

## 17. M2 剩余

1. 在 `d3_service.c` 的 nvdrv ioctl 处理里保存 channel fd ↔ `bind_id`，把
   pbuffer 地址/size 通过桥提交
2. 桥里用 GMMU `GetPointer` 读 pushbuffer，组 `Tegra::CommandList` 后
   `PushGPUEntries`（空列表已验证会阻塞，必须带真实命令）
3. 真实 `FramebufferConfig` + `RequestComposite` 出第一帧

## 18. M2 探查：GPU 可见内存必须来自 `Core::DeviceMemory`

把 guest 地址当作宿主指针（NCE 风格，identity map）后，尝试：

```cpp
gmmu.RegisterProcess(&app_memory);
gmmu.Map(0x100000, page_addr_in_process, 4096, asid);
gmmu.GetPointer<u8>(0x100000);
```

真机上进程直接死亡（无新日志、无稳定 tombstone 行）。原因在
`DeviceMemoryManager::Map` 的实现：

```cpp
auto phys_addr = static_cast<u32>(GetRawPhysicalAddr(ptr) >> page_bits) + 1U;
```

`GetRawPhysicalAddr` 是 `ptr - physical_base`，而 `physical_base` 是
`DeviceMemory.buffer`（4 GiB 稀疏 memfd）的基址。传进来的栈页地址不在该窗口内，
差值溢出成巨大的 `u32`，页表项因此损坏。

结论：**能进 GPU 页表的地址必须坐落在 `Core::DeviceMemory` 的 backing 里**
（即 nvmap/显存分配要从这块 memfd 划分），不能是任意 malloc/栈地址。

当前设备包稳定（bridge + channel + renderer 均在，清屏色在屏）。

## 19. M2 打通：GPU 地址翻译（真机验证）

按上一节的结论，把 GPU 可见页改成 `Core::DeviceMemory` backing 内的偏移
（256 MiB 起，避开内核保留区），再走 `RegisterProcess → Map → GetPointer`：

```
I d3gpu: memtest: gpu=0x100000 translated=0x6c90000000 ok=1
```

`0x6c90000000 = backing(0x6c80000000) + 256 MiB`，写进去的 `0x5a/0xa5` 读回一致。
也就是 **GPU 页表翻译链路（DAddr → 宿主指针）在真机上可用**，这正是 pushbuffer
读取和 framebuffer 扫描出来要用的通路。

## 20. 下一步（M2 收尾）

1. 用同一套 Map 把 pushbuffer 放进 backing，桥里读命令字 → 组
   `Tegra::CommandList` → `PushGPUEntries`（不能再提交空列表）
2. nvdrv ioctl 里把 pbuffer 的 GPU 地址/长度传给桥
3. 真实 framebuffer（backing 内的 BGRA 缓冲）→ `RequestComposite` → 第一帧

## 21. M2 探查：`RequestComposite` 会阻塞（不是崩溃）

把 640x360 的 RGBA 渐变写进 DeviceMemory backing、`Map` 到 GPU 地址 0x200000，
再调 `GPU::RequestComposite({framebuffer}, {})`：

- 真机上调用**不返回**（后续日志无输出、进程存活、无 tombstone）
- 与空 `PushGPUEntries` 的现象一致：GPU 线程侧的提交/呈现路径在没有
  真实的通道工作流时不会完成

结论：composite 不能作为第一个被调用的入口，必须先有 guest 侧的真实工作流
（通道提交 → GPU 线程 → rasterizer → present），也就是 M2 的 pushbuffer 路径
必须先通。当前设备包已回退到稳定版本（渲染器 + 通道 + 地址翻译自检均在）。

## 22. 下一轮计划

1. 用 backing 里的 pushbuffer 组真实 `Tegra::CommandList`（不能空列表）
2. 通过 nvdrv ioctl 的 fd ↔ `bind_id` 映射把 pbuffer 交给桥
3. pushbuffer 生效后再谈 composite（此时 GPU 线程已具备工作流）

## 23. 关键修复：GPU 线程改异步，阻塞消失

`Tegra::GPU(system, is_async=false, ...)` 会让 `SubmitList` / `RequestComposite`
在同步模式下等 GPU 线程完成——空列表或没有后续工作流时就是永久阻塞。
适配层改为 `is_async=true` 后：

```
I d3gpu: composite: 640x360 framebuffer submitted (gpu=0x200000)
```

调用立即返回、进程存活。**这是之前两次"卡住"的真正原因**（不是逻辑死锁）。

## 24. 当前状态与下一步

- composite 已被接收，但截屏仍是 M1 的清屏色（三处采样均为 `(40,88,209)`），
  说明 present manager 还没有真正把这一帧 blit 上屏
- 下一步要查 `vk_present_manager` / `vk_blit_screen` 的驱动条件：
  `OnFrameDisplayed`、swapchain 的 `Present` 是否只在 `SwapBuffers` 时触发，
  以及 `EmuWindow::OnFrameDisplayed` 是否需要被调用
- pushbuffer 路径同样受益于异步模式（空列表不再阻塞），可以继续做真实命令提交

## 25. composite 未上屏：排查结果

线程视角确认 Eden 的线程都在跑（`adb shell ps -T`）：

```
VulkanWorker / VulkanPresent / GPUFencingThrea...
```

又试了「去掉 M1 的 clear，让渲染器独占 surface」：SurfaceView 变成**纯黑**
`(0,0,0)`，说明 Eden 的 composite 已提交但没有把内容 present 到窗口（黑帧，
而不是清屏帧）。恢复 clear + renderer 之后画面回到 `(40,88,209)`。

即：composite → `present_manager.Present(frame)` 这段还没走通（可能卡在
`swapchain.Present` 的获取/呈现条件，或 blit 输出为空）。下一步需要在
`vk_blit_screen.cpp` / `vk_present_manager.cpp` 里加点日志，定位帧在哪一步丢失。

## 26. 当前稳定状态（真机验证）

```
vk-clear: swapchain 2484x475 images=4 / presented result=0
renderer: Vulkan::RendererVulkan ready (vendor=Qualcomm)
channel: allocated and initialised
gpu bridge ready, channel=1
memtest: gpu=0x100000 translated=0x6c90000000 ok=1
composite: 640x360 framebuffer submitted (gpu=0x200000)
截屏中心 (40,88,209)
```

## 27. 根因（第二个）：`GPU::Start()` 从未被调用

临时给 Eden 打日志后（已回滚，`reference/eden` 是只读克隆）发现：
`RendererVulkan::Composite` **根本没执行**。原因：

```cpp
void GPU::Start() {
    Settings::UpdateGPUAccuracy();
    gpu_thread.StartThread(*renderer, renderer->Context(), scheduler);
}
```

`BindRenderer` 只做绑定，GPU 命令线程由 `GPU::Start()` 显式启动。我们之前只调了
`BindRenderer`，所以 `SubmitList` / `RequestComposite` 全部进了队列却没人消费
（同步模式下表现为"卡住"）。

补上 `gpu.Start()` 后真机日志：

```
I d3render: Composite: got frame, drawing
I d3present: Present(frame=0xb4...) thread_mode=1
```

即 composite 已经跑到 `Present()`，但 `PresentThread` 的 `CopyToSwapchain`
仍未执行（`thread_mode=1` 时 frame 通过 `scheduler.Record` 入队，依赖
scheduler worker 实际执行回调）。下一个待查点就是这条队列回调何时被 flush。

## 28. 当前状态

- `gpu.Start()` 已加入 host 适配层并真机验证（进程存活、各步骤日志齐全）
- Eden 侧的临时日志已全部回滚（`git -C reference/eden checkout -- ...`）
- 画面仍是 M1 清屏色；present 线程未消费帧

## 29. 第一帧经 Eden 渲染器上屏（真机截屏）

上一节定位到：`PresentManager::Present` 在 `use_present_thread` 模式下通过
`scheduler.Record` 入队，回调要等**下一次** flush 才执行；单次 composite 永远
到不了 present 线程。连续提交两次后，真机截图出现渐变内容：

```
(1280,480)=(86,134,113)   (1280,544)=(125,135,238)
(1024,512)=(102,106,105)  (1536,512)=(97,161,90)
```

证据图：[`d3-android/gpu/probe/m3-composite-2026-10-18.png`](../d3-android/gpu/probe/m3-composite-2026-10-18.png)

也就是 **`RequestComposite → BlitScreen → PresentManager → swapchain.Present` 整条
链路在真机上跑通**，画面来自我们自己写的 640x360 RGBA framebuffer（不是 M1 的
纯色清屏）。这是 M3 的"渲染管线就绪"，下一步是让 guest 的命令/帧buffer 驱动它。

## 30. 下一步

1. 把两次提交的 hack 换成正确时机：guest 每帧都会 flush，天然满足"下一次 flush"
2. pushbuffer → `PushGPUEntries` 接入（GPU 线程已启动）
3. nvdrv ioctl ↔ 通道 fd 映射

## 31. 真机现状：guest 在到达 nvdrv 之前就退出

用 `--ez autostart true` 跑完整启动，约 1 秒后进程消亡
（`ActivityManager: handleAppDied`），日志停在：

```
t16430: StartThread spawned
t16433: thread: start ... WaitSynchronizationN count=0 -> timed out
（随后进程退出，无 nvdrv:: 日志）
```

也就是说 **Eden 渲染管线（M0–M3 渲染侧）已经可用，但 guest 还没走到 GPU 初始化**
就退出了；上一轮之前文档记录过这个"非 guest 线程上退出"的老问题。

因此 M3 的"guest 驱动的第一帧"当前被两件事阻塞：

1. guest 提前退出（需要重新定位退出原因：信号链 / 线程握手 / 服务缺失）
2. nvdrv ioctl 实现（目前是 stub，只记 fd/cmd）

## 32. 建议顺序

1. 先把 guest 退出问题查清（用现有 `d3-crash.txt` / tombstone / logcat 的退出原因）
2. 再实现 nvdrv 的 Open/Ioctl 子集（NvGpuAS / NvGpuChannel 的 Alloc/Map/Submit）
3. 最后把 pushbuffer 接到已经跑通的 `PushGPUEntries`

## 33. 退出原因：不是信号（也没有 tombstone 可读）

- `/data/tombstones` 需要 root 读；`d3-crash.txt` 与 `files/runtime/logs` 都是空的
- 加了诊断用 fault logger（`SIGSEGV/SIGBUS/SIGILL/SIGABRT` → 打 `pc/lr/sp/fault` 后恢复默认），
  用 autostart 跑完整启动：**没有触发任何 fault 日志**，进程仍在一个 SVC 序列后消失
- 因此 guest 更可能是走了 **自愿退出路径**（`ExitProcess` 类 SVC 或 host 侧 `_exit()`），
  而不是崩溃信号

## 34. 下一步

1. 在 host 的 SVC 分发里给"退出类"系统调用加日志（找到是哪条 SVC / 哪个返回码让流程终止）
2. 确认退出是否由 guest 主动调用（`svcExitProcess` / `svcExitThread`）触发
3. 若是主动退出，回溯调用点（符号级）定位 guest 为什么会走到那里

## 35. 信号 11 存在，但我们的 handler 收不到

- `Zygote: Process ... exited due to signal 11 (Segmentation fault)` 明确说明是 SIGSEGV
- 把 fault logger 临时改为**总是安装**并去掉 `SA_ONSTACK` 后仍然没有任何 `d3fault` 日志
  → 该信号没有走到我们的处理器：很可能所在线程**屏蔽了 SIGSEGV**，或崩溃发生在
  信号处理上下文里（嵌套），内核直接按默认动作终止
- 目前日志只能看到最后一条 `WaitSynchronizationN count=0 -> timed out`

## 36. 下一轮取证方案

1. `adb shell am set-debug-app -w com.d3mobile.host.recovery` 后用 lldb 附加，
   直接在 SIGSEGV 处拿 pc / 调用栈（最可靠）
2. 或用 `adb bugreport` 取出 tombstone（`/data/tombstones` 需要 root 才能直接读）
3. 拿到 pc 后用 `reference/d3-symbols` 的符号表换算 guest 偏移

## 37. GMMU 用法修正：`Map` 前必须先 `AllocateFixed`

dropbox 里取到的 tombstone（旧包）显示，之前的一类崩溃其实是**我们自己的 memtest**：

```
#01 AssertFatalImpl()
#02 Common::SparseLargeVector<unsigned>::GetAndFault
#03 Core::DeviceMemoryManager<MaxwellDeviceTraits>::Map(...)
#04 d3_gpu_bridge_memtest
```

`DeviceMemoryManager::Map` 假定该 GPU 地址段已由 `Allocate`/`AllocateFixed` 分配；
直接 `Map(0x100000, ...)` 会触发 `GetAndFault` 断言。已在两处测试代码里补上：

```cpp
gmmu.AllocateFixed(kGpuAddress, 4096);
gmmu.Map(kGpuAddress, (VAddr)page, 4096, asid);
```

## 38. 取证手段确认可用

`adb shell dumpsys dropbox --print` 可以直接拿到 tombstone（不需要 root），
包含完整寄存器与 backtrace —— 这是后续定位 guest 崩溃的主要手段。

注意：dropbox 里可能残留旧构建的记录，定位时要核对时间戳与 build 路径。

## 39. 崩溃取证开关：`<data root>/no-handler`

host 的 `install_crash_handler()` 里有一个显式开关：

```c
static int tombstone_mode(void) {
    struct stat st;
    return stat(D3_DATA_ROOT "/no-handler", &st) == 0;
}
...
if (tombstone_mode()) { info("crash handler disabled, using debuggerd"); return; }
```

- 存在 `no-handler` 文件 → host 不装处理器，交给 debuggerd 出 tombstone
  （但本机 dropbox 只记录到 02:41:50 为止，之后的 guest 崩溃没有被收录）
- 不存在 → host 处理器生效，理应打印 trace / 写 dump；当前观察不到任何输出，
  需要确认 `D3_DATA_ROOT` 的实际编译值（`files/runtime` 只有空的 `logs/`）

本轮结论：guest 的 SIGSEGV 现场目前两条取证通道都不完整（dropbox 无新记录、
host 处理器无输出）。下一步先把 `D3_DATA_ROOT` 与实际落盘路径对齐，再决定用
`no-handler`（debuggerd）还是 host 处理器。

## 40. guest 已走到 GPU 初始化边界（重要）

把 `D3_DATA_ROOT` 对齐到 app 可写目录后
（`build_host.py --sandbox-root /data/user/0/com.d3mobile.host.recovery/files/runtime`），
可以从 `files/runtime/data/logs/d3-service.log` 读到完整 IPC 记录。关键尾部：

```
IApplicationFunctions::GetGpuErrorDetectedSystemEvent -> handle 0x1005
svc cmif port=appletOE cmd=0 ... words0..15=... 0x1005 ...
t17669: svc #0x18 (WaitSynchronizationN) count=1 handle=0x6 -> index 0
<进程 SIGSEGV>
```

即 guest 已经完成 applet/GPU 错误事件注册，在**等待返回后**的下一条路径上崩溃。
这比"死在 nvdrv 之前"更精确：它死在 **GPU 初始化刚起步**的位置，还没发出
`nvdrv::Open`。

## 41. 下一步取证（host 自带 tracer）

host 里有 tracer 机制：`TRACE_PATH = D3_DATA_ROOT "/logs/d3-trace.txt"`，
由触发文件开启（见 `d3_host.c` 的 tracer 段），能记录致命信号前后的 256 个事件。
下一步开启 tracer 跑一次 autostart，拿到崩溃前最后几条事件（SVC / IPC），
再用 `reference/d3-symbols` 换算 guest pc。

## 42. tracer 与 debuggerd 两条路都没产出（本轮实测）

1. 创建 `<D3_DATA_ROOT>/trace` 触发内置 tracer 后跑 autostart：
   `files/runtime/logs/d3-trace.txt` **不存在**（tracer 子进程没有落盘，
   可能是 ptrace attach 被 SELinux 拒绝，或崩溃早于 tracer 首次写入）
2. 改成 `<D3_DATA_ROOT>/no-handler`（由 debuggerd 接管）后跑：
   `dumpsys dropbox` 里**没有新增** `data_app_native_crash`（最新仍是 02:41:50）

同时确认 host 没有改 `PR_SET_DUMPABLE` / `core_pattern`。

## 43. 下一步

1. `adb shell ls -lt /data/tombstones` 看是否有新文件；有则用
   `dumpsys dropbox --print SYSTEM_TOMBSTONE` 按时间戳取内容
2. 若无新 tombstone，说明 debuggerd 未介入（SELinux / dumpable 限制），
   改用 host 内置处理器 + 直接写 pc/backtrace 到 `d3-crash.txt`
   （`install_crash_handler` 分支，需要把写文件路径改成可写目录）
3. 或者用 `set-debug-app -w` + lldb 附加

## 44. 崩溃落盘路径修正（仍未触发）

host 的崩溃写盘路径是：

```c
#define CRASH_PATH         D3_PRIVATE_ROOT "/files/d3-crash.txt"
#define CRASH_PATH_FALLBACK D3_PRIVATE_ROOT "/cache/d3-crash.txt"
#define CRASH_PATH_SDCARD  D3_DATA_ROOT "/logs/d3-crash.txt"
```

之前的构建只传了 `--sandbox-root`，`D3_PRIVATE_ROOT` 变成
`.../files/runtime/private`（不存在）。本轮改为显式指定：

```
--data-root /data/user/0/com.d3mobile.host.recovery/files/runtime
--private-root /data/user/0/com.d3mobile.host.recovery
```

重装后跑 autostart，`files/` 下仍**没有** `d3-crash.txt`，说明崩溃处理器
本身没有被调用（与前面"信号没走到我们的 handler"一致），而不是路径问题。

## 45. 结论与下一步

guest 的 SIGSEGV 同时满足：
- 我们的 SIGSEGV handler 不执行
- debuggerd 不生成新 tombstone（最新仍是 02:41:50）
- tracer 子进程不落盘

这种组合强烈提示崩溃线程**屏蔽了这些信号**（或进程当时已处于不可 dump 状态）。
下一步建议：
1. 在 host 的 guest 线程创建处打印/清除 `pthread_sigmask`（确认是否屏蔽）
2. 若是屏蔽，取消对 SIGSEGV 的屏蔽后再复现
3. 或者用 `set-debug-app -w` + lldb 在启动前附加，绕过信号处理器

## 46. 崩溃根因缩小：guest 主动断言 `Break(0)`（sdk+0x193ad8）

从 dropbox 的 tombstone（`tombstone_17`，pid 18354，线程 `d3-guest`）与 D3Host 日志：

```
t...: d3_host_table ... bias 6e0e490000
t...: Break assertion reason=0 arg=... size=4 lr=0x6e0e623ad8 (sdk+0x193ad8)
E D3Host: guest assertion Break(0) lr=0x6e0e623ad8
backtrace:
  #00 abort
  #01 fail()
  #02 d3_hle_dispatch+5164
  #03 <anonymous>
```

即：guest 执行了 `brk #0`（HVC/break 语义的断言），host 的 Break 处理把它转成
`fail()` → abort。**不是随机 SIGSEGV，而是 guest 自身的断言失败。**

`lr = sdk+0x193ad8`。用 `sdk.symbols.json` 查最近符号：
`_ZN2nn2ec6detail15ShowShopPageArg14SetCallbackUrlEPKc` @ 0x193a10（+0xc8），
但该符号只有 0x?? 大小未知，实际断言点很可能在相邻未导出函数里。

本地已有更新版 sdk 二进制：`reference/extract/exefs_update/sdk.nso0`，
下一轮可以直接反汇编 `0x193ad8 ± 0x100` 来确认断言位于哪个函数、断言文本是什么。

## 47. 下一步

1. 反汇编 `exefs_update/sdk.nso0` 在 0x193ad8 附近，找 `brk #0` 前的字符串/分支条件
2. 对照 `d3-service.log` 最后几条 IPC（`GetGpuErrorDetectedSystemEvent` 之后），
   确认是哪个服务返回错误触发了断言
3. 补齐对应 HLE（最可能仍是 GPU/nvdrv 初始化相关）

## 48. 断言地址的符号可疑：落在 `nn::ec` 商店代码里

把 `sdk+0x193ad8` 映射回 guest vaddr（`0x10000 + 0x193ad8 = 0x1a3ad8`）后：

- `libd3guest.so` 已被剥离到只剩 `.dynstr/.dynsym/.rela.dyn`，**没有可反汇编的 section**
- `reference/extract/exefs_update/sdk.nso0` 用 `parsenso.py` 的 `to_file()` 可以定位字节，
  但本机没有 `capstone` 也没有 `llvm-mc`，`llvm-objdump` 不能直接反汇编裸二进制
- 用 `sdk.symbols.json` 看该偏移附近，**全是 `nn::ec` 商店（ShowShopPage / ShopServiceAccessServer）代码**：

```
0x193980  nn::ec::detail::ShowShopPageArg::SetUid
0x193a10  nn::ec::detail::ShowShopPageArg::SetCallbackUrl
0x193b00  nn::ec::detail::ShowShopPageArg::SetCallbackableUrl
```

暗黑3 启动时不会去调 eShop，所以更可能的解释是：**`sdk+offset` 的基准不对**
（host 的 `module_of()` 用的 sdk base 与 README 里 "sdk 位于 vaddr 0x10000" 的假设不一致），
或者 lr 落在内联断言里、符号表缺失该内部函数。

## 49. 下一轮

1. 用 host 日志里的 `bias` 与 `module_of()` 输出，反推 sdk base 是否等于 `0x10000`
   （打印 `module_of` 用的基表）
2. 装 `capstone`（pip）或用 `llvm-objdump` + 手写 ELF 包装，反汇编
   `sdk.nso0` 在目标偏移附近，直接看 `brk #0` 前的字符串/条件
3. 若基准确实偏移，修正后重新换算断言位置
