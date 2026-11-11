# Android 源码与接口说明

当前构建、状态分别见 [BUILD.md](BUILD.md) 与 [STATUS.md](STATUS.md)。本文件保留早期交接中仍有用的接口约定，不把历史启动阻塞作为当前问题。

## 运行路径

原始 ARM64 guest 在 Android ARM64 设备执行；host 接管 Horizon SVC/IPC、线程/TLS、文件和图形服务。GPU 工作通过 nvdrv/GPFIFO 交给 Eden 的 Maxwell、shader recompiler 和 Vulkan 栈。

| 范围 | 正式源码入口 |
| --- | --- |
| guest、信号、SVC、线程/TLS | `android/host/d3_host.c`、`d3_sync.c`、`hook_stub.S` |
| IPC 与服务 | `d3_service.c`、服务相关 `.inc`、`d3_service_names.h` |
| GPU | `d3_nvdrv.c`、`android/gpu/host/` 的 GPU bridge、renderer、window |
| 音频 | `d3_audio.c`、`d3_audio_service.inc`、JNI |
| 内容识别 | `d3_content.h`、AOC 枚举和 mount/path hooks |
| 建角、键盘与存档 | `d3_keyboard_service.inc`、`d3_save_ops.inc` |
| 生命周期、设置与输入 | `d3_jni.c`、`android/app/src/com/d3mobile/host/` |
| 原生显示补丁 | `d3_display.h`、`d3_host.c` 中经指令校验的 patch/trampoline |

旧 `*_minimal.c`、`*_new.*`、`d3_table.c`、`jni_template.c` 不属于正式构建来源，不应替代当前源码。

## 保留的约束

- 信号链要区分 guest 和 ART/其他 host 线程；非 guest 故障交还 Android 信号处理链，不用吞错代替兼容实现。
- HID 共享内存保留服务端可写、guest 只读的双视图。曾有只读映射写入导致 A 键崩溃，不能退回单一权限布局。
- guest 内部的启动/构造路径由实际 ABI 决定，不能重复调用初始化数组。历史 TLR/`d3_table` 推断不能覆盖现有实现。
- 图形一致性依赖 CPU/GPU 修改跟踪和精确页快照；空置 `RasterizerMarkRegionCached`/`GatherGPUDirtyMemory` 一类回调会破坏真实画面。
- 内存 SVC 的映射/权限变更与区域表重建、QueryMemory 使用同一互斥锁；启动时的可执行地址查询也读取一致快照。不能让不同线程同时修改或排序 `g_reg`，否则会产生虚假重叠、查询空隙和启动 abort。
- guest 原件保持不变。运行时分辨率/FOV 补丁必须先校验 BuildID/指令、调用目标与 trampoline 空间；失败不做部分写入，禁止重复应用。
- X200 Pro 菜单需覆盖稳定和过渡两条相机路径，当前菜单 FOV scale 为 0.78125；不据此修改局内相机。该取景收窄会减少外围覆盖。

## 运行时内容

`D3_CONTENT_ROOT` 默认 `/data/local/tmp/d3romfs`，独立于应用私有 runtime。AOC 只承认已逐文件校验并写完成 marker 的安装；保持只读、路径穿越与卸载检查。

音频 guest 为 48kHz、6 声道 PCM，host 使用 AAudio 并 downmix。非零 PCM 和无 xrun 只能证明软件链路工作，仍需对白、设备切换及声画同步听验。

各 profile 的 `data-root`/`private-root` 必须和包名一致，存档保存在对应 runtime 下。应用重建 Surface 时应重新绑定仍在运行的 guest；force-stop 后的加载不能计为同进程恢复。

## S2Arm 图形路线评估（2026-11-11）

目标限定为 Android《暗黑 3》的正确画面、持续帧率与功耗。本次查阅上游 `dadb916f3aabab983c7ea1a1b641c2c6b0adcd60`，并按用户提供的留存源码 `out/research/S2Arm/`（`3584904a17d86886bb0346ded50fea1997ee23a4`）核对生产图形接线。源码快照与 APK 身份分别记录，留存 APK 账本没有提供二者的可复现构建绑定。

| 比较项 | 当前 Android 路径 | S2Arm 路径及结论 |
| --- | --- | --- |
| CPU | 已直接执行 ARM64 guest，host 应答 SVC/IPC | 同为 ARM64 原生执行；不能把“没有 CPU 模拟器”当作相对本项目的新收益。改写、TLS 与系统服务的具体成本仍需采样 |
| 图形入口 | 游戏 NVN 实现产生 nvdrv/GPFIFO，Eden 处理 Maxwell 命令和 shader，再落到 Vulkan | NVN 直连接管 `nvnBootstrapLoader`，经共享 NVN 前端、记录回放与 Android Vulkan 后端绘制；有机会减少底层 GPU 命令处理和资源识别成本 |
| 内存一致性 | cached 页精确快照扫描，实验 write-watch 尚未完成性能验收 | 有资源级写入通知、脏页保护与上传跟踪；仍需处理 CPU/GPU 写入、别名、纹理转换和同步，不能直接移除一致性维护 |
| 暗黑 3 证据 | 既有移动、战斗、存档、宽屏和生命周期验证；范围见 STATUS | 留存截图已有世界场景与 HUD，用户明确确认使用 NVN 直连；这是既有测试证据，本轮没有重跑游戏。尚缺同条件帧率、功耗和长期正确性对照 |
| 离线着色器 | 使用现有 Eden 翻译与缓存链 | 留存构建日志明示离线 LibPack skipped，且未提供 `S2A_VULKAN_PROFILE`；文件账本仅有直连图形描述符，没有离线 shader 包，不能套用 Apple 平台的预编译收益 |

本地证据为 `out/android/s2arm/artifact.json`、`build-stages.log`、`20261111-s2arm-d3-ingame.png` 与 `game.apk`。APK 实算 SHA-256 与账本一致：`fa6ae5a5fd8e29ee32e9650ae78dcd6f5b0467848ce1e18b0236880adfed7e44`；包名 `org.s2arm.game.t01001b300b9be000`，游戏版本 `2.7.7.92380`。构建环境显式设置 `S2ARM_ANDROID_VK_ENGINE=1`、`S2ARM_ANDROID_VK_BACKEND=nvn_vk`，资源账本含 `resources/shaders/vulkan/direct/graphics.v1.json`。编译配置和描述符本身只能证明具备直连条件，实际模式由上述用户确认补足。

上游 [性能证据](https://github.com/jhaizhou-ops/S2Arm/blob/dadb916f3aabab983c7ea1a1b641c2c6b0adcd60/docs/validation/EVIDENCE.md) 的 6.4 分钟是暗黑 3 出包时间；43.3 FPS / 6.63 W / 0.153 J 每帧来自另一款 Switch 2 游戏和 iPhone，不能用作本项目 Android 暗黑 3 的功耗对照。现有 45.94 composite FPS / 6.674 W 也只是本项目一次带诊断的短窗口，不能与之跨游戏、跨设备比较，更不能据此承诺 60 FPS / ≤4.5 W。

迁移技术上可行，优先候选是保留本项目 D3 host、输入、内容/存档和音频，另接 NVN→Vulkan 图形后端。主要可复用生产模块为：

- `graphics/nvn/gfx/nvn/` 的 NVN 语义、命令记录和资源跟踪。
- `android/native/nvn/mtl_vk_shim.c`、`mtl_vk_adapter.c` 与 `nvn_vk_*` 的 Vulkan 提交、纹理/缓冲、同步和呈现；名称中的 `mtl` 不代表这里使用 Metal。
- 与这些模块匹配的 shader 编译接口、特化信息和缓存。暗黑 3 可按实际用到的功能和 shader 缩小范围，不能把一次静态抽取数量当作全场景覆盖。

这属于独立图形后端适配，不能直接替换一个 SO。当前 `load_guest` 载入保留的 ELF 并安装 D3 hook；S2Arm 包使用 `main/sdk.patched.bin` 与 `android-sp-safe-v1` fixup/gate。需要适配 guest/host 调用与 TLS、返回的 NVN 函数指针、内存池/别名和 fault 链、shader 编译、Surface/驱动与退出清理。已有 SDK 符号表能定位 `nvnBootstrapLoader`，但接入仍须核对实际 guest 的 BuildID、布局与指令；Eden 专用的场景缩放补丁也不能原样沿用。复制代码时保留 Apache-2.0、NVN 前端 MIT 及相关第三方声明。

结论是将 NVN 直连列为针对暗黑 3 功耗的优先验证方向，尚不能认定其在目标设备上更省电。本轮未迁入运行代码。先以既有 S2Arm 直连包与当前正确画面的基线做串行 A/B/A：对齐游戏版本、存档/动作、实际场景/UI 分辨率与比例、帧率目标、驱动、亮度和热状态，各自预热缓存、关闭诊断并拔线采样；同时验证场景/HUD、动作与可观察业务结果。稳定帧时和整机功耗重复优于基线后，再迁图形模块并完成长时战斗验收。无需为此引入多游戏库、通用启动器或替换整套系统服务。

### 可独立验证的节能候选

以下为源码调查得到的候选，并非已测得的节电收益；其中前两项可在现有 Eden 路径验证，不必等待 NVN 后端迁移。

1. **减少无变化页扫描和保护操作**。既有一次窗口每轮扫描 37281 页、变化 87 页（约 0.23%）、耗时 10.579 ms。S2Arm 的 `nvn_dirty.c` 将连续页的保护操作合并，并为资源提供写入范围/子资源通知；`nvn_vk_texcache.c` 分别维护 CPU/GPU 写入和局部更新。现有元数据/快照拆分候选先完成实机验证，再结合真实 fault、mprotect 和调度成本选择保护粒度，保留精确比较与审计。旧 write-watch 已出现 CPU 降低而 FPS 变差，不能仅按扫描耗时选择方案。
2. **按帧期限提示 Android 调度器（ADPF）**。S2Arm 的 `adpf_hint.c` 使用 `APerformanceHint_*` 管理关键渲染线程；`mtl_vk_shim.c` 在渲染任务开始采时、drain 后且 acquire/呈现节拍等待前结束工时，并丢弃没有匹配呈现的旧样本。现有 GPU host 未见该接口接线。接入时按真实工作线程、目标帧间隔和前后台/Surface 生命周期管理，不把主动限帧睡眠算进工作量，不硬锁大核或常驻高频；收益及 OEM 响应需同条件验证。
3. **背压、批量提交与临时内存复用**。S2Arm 的 `shim_enqueue` 对满队列使用条件变量等待并拒绝无限增长，`nvn_vk_threadbuf_acquire` 复用线程临时存储，descriptor cache 按完整 key/generation 复用。当前限帧等待在 `d3_gpu_present_guest` 的 fence 等待之后、composite 之前，应采样确认是否仍有过量提前生产或反复提交。Eden 已有缓存和异步处理，先定位仍在重复的分配、descriptor 更新、上传和全局等待，不能直接删除同步或重复造缓存。
4. **暗黑 3 着色器与管线预热**。用目标 Vulkan profile 和实际游戏路径收集的 shader/特化组合建立可失效的缓存，在加载期预热常见管线；按游戏 BuildID、设备/驱动及翻译器版本区分。留存 S2Arm 包未带离线 shader 包；这项主要减少首遇卡顿和编译峰值，稳定热缓存运行是否更省电另测。
5. **Mali 的 GPU 像素与带宽预算**。这是结合本项目设备能力提出的扩展候选，并非 S2Arm 已证收益：维持原生 UI，对 3D 场景单独试低分辨率或受控 VRS，同时检查附件 load/store、render-target 切换和可消除的中间拷贝。VRS 的实际功能/格式支持和画质必须逐项验收；FSR 世界全黑问题仍未解决，不能作为可用节能方案。
6. **按暗黑 3 场景设置帧率策略**。若产品接受菜单较低帧率，可试菜单/背包 30 FPS、战斗 60 FPS，并核对屏幕实际刷新模式而非只发请求。只减少渲染负荷，须验证输入、动画/逻辑速度、音频和后台恢复；菜单节电不能计作持续战斗 60 FPS 的节电收益。

当前优先级为扫描/写跟踪与 ADPF 的小范围串行对照，其后验证 GPU 像素/带宽与 NVN 直连；队列、缓存及预热按采样中的重复工作和首遇卡顿决定投入。所有候选继续用同场景画面、帧时和拔线整机功耗共同验收。

## 实验项

### 文字与输出尺寸

1.0× 仍是全局清晰基线；偏好值 `625/75/875` 分别将匹配的 3D 场景附件降到 0.625×/0.75×/0.875×，UI 和文字附件保持原尺寸。默认合成使用传输线性放大，避开 vivo GameLib VSR 的宿主 render pass/描述符崩溃点。绕开 VSR 后，实验 EASU + RCAS 在标题/过场可见，用户仍确认世界场景全黑；场景缩放不能被表述为已完成可用 FSR。FP32 以及输入/中间图/目标的像素回读用于后续定位，尚未在世界场景验证。

`PresentationPolicy` 统一 guest 和 Surface 尺寸。X200 Pro 的 1.0× 宽屏 guest 为 2000×900，Surface 同为 2000×900，去掉此前固定 1600×720 的中间下采样；1.5× 的 Surface 以物理屏幕尺寸为上限。Activity 重建时使用本进程已配置的 guest 参数，避免未生效的设置改变现有渲染缓冲尺寸。软件帧率上限在宿主 composite 前按单调时钟期限实现；屏幕刷新请求独立设置且不证明实际刷新模式或稳定上屏帧率。

这些是渲染策略与尺寸约束，文字视觉效果、功耗和持续原生 60fps 仍须分别实测。

### GPU 与驱动

`gpu-write-watch` 使用页权限与 fault 跟踪来减少扫描，仍有未解决的菜单临界区等待 abort 历史。后续“连续 16 轮不变才 watch、256 轮 audit”通过过独立测试，未完成完整实机集成验收，正常配置保持关闭。

首次布防的 `mprotect(PROT_READ)` 可能先于 `Active` 标志发布完成。写故障处理器遇到 `Busy` 必须等待该标志发布后再判断是否属于跟踪页，不能提前把这类真实写故障交给致命故障路径。对应回归在测试翻译单元中延迟真实保护调用的返回，覆盖另一线程在该窗口写入并恢复的行为；生产代码不包含测试钩子。

缓存候选把页元数据与连续的精确快照分开，以减少干净页遍历的缓存/TLB 成本，并让轻量 watch 扫描不唤醒两个工作线程。每 256 轮仍并行全量审计；普通全扫描保留。旧 trace 的 full/watch/full-repeat 对照中，watch 窗口的关键 CPU 线程频率计数降低，VulkanWorker 由主要在 CPU 4/5 运行转为跨小核运行，CPU 时间约 1.07→2.00 秒/10 秒，runnable 等待约 0.52→0.79 秒。这支持进一步检查关键线程调度/Android Performance Hint，但不能直接认定因果；这些 trace 没有有效 GPU 频率或 mprotect 事件。复核提取在 `out/android/fsr-contract/cache-layout/prior-scheduler-comparison.json`。新候选仅编译，实机正确性和收益均待测。

`local/android/vendor-vsr/` 保存旧调查的 GameLib APK、VSR 层和来源/哈希清单。层中可见 `VrsServiceVK`、`vkCmdSetFragmentShadingRateKHR`、着色率图与 render pass 替换路径，同时存在超分着色器和按游戏的 shader/纹理/设备配置。包名白名单只证明能触发注入，不能证明《暗黑 3》适配正确或能省电；配置不匹配仅为待验证假设。

离线 `device-vulkan.json` 报告 Mali-G925 支持 `VK_KHR_fragment_shading_rate` 的 pipeline/primitive/attachment 三项能力，最大 4×4，且有 fragment density map。当前 Eden 只在识别 NVIDIA 架构时查询过 VRS 属性，尚未在设备 feature 链、绘制管线或命令封装启用 VRS。可探索直接给场景的几何绘制使用 2×1/1×2 着色率，UI/文字/最终合成保持 1×1；这能保持覆盖/深度尺寸并减少片段执行，和 FSR 的重建开销不同。接入必须重新查询实际加载的 Mali 驱动的可用尺寸与采样组合，排除副作用/互锁/逐样本语义，并为每次绘制显式恢复 UI 的 1×1。尚未实现或实测，不能将系统能力报告写成已启用 vivo VSR。

自定义 Mali 补全包使用本机已有实现，不代表升级了驱动版本。libadrenotools 隔离加载及状态以进程 maps、枚举与真实渲染日志联合核对；仅出现库映射不能证明每次游戏 Vulkan dispatch 都经过目标层。

## 历史技术细节

以下文档保留早期实现的原理与当时验证范围，临时路径和阶段状态不再作为当前入口：

- [信号链](architecture/SIGNAL_CHAIN.md)
- [同步原语](architecture/SYNC.md)
- [时间服务](architecture/TIME_SERVICE.md)
