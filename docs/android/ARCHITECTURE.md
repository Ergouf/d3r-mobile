# Android 源码与接口说明

当前构建、状态分别见 [BUILD.md](BUILD.md) 与 [STATUS.md](../STATUS.md)。本文件保留早期交接中仍有用的接口约定，不把历史启动阻塞作为当前问题。

## 运行路径

原始 ARM64 guest 在 Android ARM64 设备执行；host 接管 Horizon SVC/IPC、线程/TLS、文件和图形服务。GPU 工作通过 nvdrv/GPFIFO 交给 Eden 的 Maxwell、shader recompiler 和 Vulkan 栈。

| 范围 | 正式源码入口 |
| --- | --- |
| guest、信号、SVC、线程/TLS | `d3-android/host/d3_host.c`、`d3_sync.c`、`hook_stub.S` |
| IPC 与服务 | `d3_service.c`、服务相关 `.inc`、`d3_service_names.h` |
| GPU | `d3_nvdrv.c`、`d3-android/gpu/host/` 的 GPU bridge、renderer、window |
| 音频 | `d3_audio.c`、`d3_audio_service.inc`、JNI |
| 内容识别 | `d3_content.h`、AOC 枚举和 mount/path hooks |
| 建角、键盘与存档 | `d3_keyboard_service.inc`、`d3_save_ops.inc` |
| 生命周期、设置与输入 | `d3_jni.c`、`d3-android/app/src/com/d3mobile/host/` |
| 原生显示补丁 | `d3_display.h`、`d3_host.c` 中经指令校验的 patch/trampoline |

旧 `*_minimal.c`、`*_new.*`、`d3_table.c`、`jni_template.c` 不属于正式构建来源，不应替代当前源码。

## 保留的约束

- 信号链要区分 guest 和 ART/其他 host 线程；非 guest 故障交还 Android 信号处理链，不用吞错代替兼容实现。
- HID 共享内存保留服务端可写、guest 只读的双视图。曾有只读映射写入导致 A 键崩溃，不能退回单一权限布局。
- guest 内部的启动/构造路径由实际 ABI 决定，不能重复调用初始化数组。历史 TLR/`d3_table` 推断不能覆盖现有实现。
- 图形一致性依赖 CPU/GPU 修改跟踪和精确页快照；空置 `RasterizerMarkRegionCached`/`GatherGPUDirtyMemory` 一类回调会破坏真实画面。
- guest 原件保持不变。运行时分辨率/FOV 补丁必须先校验 BuildID/指令、调用目标与 trampoline 空间；失败不做部分写入，禁止重复应用。
- X200 Pro 菜单需覆盖稳定和过渡两条相机路径，当前菜单 FOV scale 为 0.78125；不据此修改局内相机。该取景收窄会减少外围覆盖。

## 运行时内容

`D3_CONTENT_ROOT` 默认 `/data/local/tmp/d3romfs`，独立于应用私有 runtime。AOC 只承认已逐文件校验并写完成 marker 的安装；保持只读、路径穿越与卸载检查。

音频 guest 为 48kHz、6 声道 PCM，host 使用 AAudio 并 downmix。非零 PCM 和无 xrun 只能证明软件链路工作，仍需对白、设备切换及声画同步听验。

各 profile 的 `data-root`/`private-root` 必须和包名一致，存档保存在对应 runtime 下。应用重建 Surface 时应重新绑定仍在运行的 guest；force-stop 后的加载不能计为同进程恢复。

## 实验项

`gpu-write-watch` 使用页权限与 fault 跟踪来减少扫描，仍有未解决的菜单临界区等待 abort 历史。后续“连续 16 轮不变才 watch、256 轮 audit”通过过独立测试，未完成完整实机集成验收，正常配置保持关闭。

自定义 Mali 补全包使用本机已有实现，不代表升级了驱动版本。libadrenotools 隔离加载及状态以进程 maps、枚举与真实渲染日志联合核对；仅出现库映射不能证明每次游戏 Vulkan dispatch 都经过目标层。

## 历史技术细节

以下文档保留早期实现的原理与当时验证范围，临时路径和阶段状态不再作为当前入口：

- [信号链](architecture/SIGNAL_CHAIN.md)
- [同步原语](architecture/SYNC.md)
- [时间服务](architecture/TIME_SERVICE.md)
