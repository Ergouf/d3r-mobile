# GPU 栈接入：当前状态与交接（2026-10-18）

## 已完成（真机验证）

- M0：Eden `video_core` + `shader_recompiler` + sirit 共 349 TU 编成 `libeden_gpu.a`（64.7 MB），
  `-Wl,--no-undefined` 通过
- 链接：`tools/build_host.py --with-gpu` 用 clang++ + 静态 libc++ 链入 `libd3host.so`
- M1：`vk_clear.cpp` 建交换链并清屏，真机截屏 `(40,88,209)`；
  证据 `gpu/probe/m1-clear-2026-10-18.png`
- 渲染器：`EmuWindowD3` + `GraphicsContextD3` → `Vulkan::RendererVulkan`，真机 `vendor=Qualcomm`
- 第一帧：`RequestComposite` 两次提交后经 BlitScreen/PresentManager 上屏，
  证据 `gpu/probe/m3-composite-2026-10-18.png`
- M2 基建：`Tegra::MemoryManager` 地址空间、`GPU::Start()`、C 桥
  （`d3_gpu_bridge_start/channel_id`）、GMMU `AllocateFixed + Map` 自检
  （`memtest: gpu=0x100000 translated=0x6c90000000 ok=1`）

## 未完成

guest 在 appletOE 初始化循环中崩溃：

```
pc_off=0x345d78  nn::os::detail::MultiWaitImpl::InternalWaitAnyImpl+0x228
fault =0x6e134be210
```

`bl 0x537490` 返回 index 或 -1；-1 是唯一"未就绪"语义。两种返回值都试过：

| 返回值 | 结果 |
|---|---|
| index 0 / success | guest 空 holder 数组越界 |
| -1 | host libc fault 0x300 |

结论：不是返回值问题，而是等待对象建模。下一轮从崩溃 dump 的 `last_kind/last_extra`
与最后几条 SVC 判断超时后的等待路径（很可能是 ProcessWideKey 或再次 wait）。

## 关键文件

- `d3-android/gpu/build_gpu.ps1`、`probe/coverage.ps1`、`tools/gen_shaders.py`
- `d3-android/gpu/host/{gpu_host,emu_window_d3,renderer_bringup,vk_bringup,vk_clear,nvdec_stub}.cpp`
- `d3-android/tools/build_host.py --with-gpu`、`build_apk.py`
- 真机取证：`d3-crash.txt`（`<private>/files/`）、`dumpsys dropbox --print`
- 符号：`reference/d3-symbols/sdk.symbols.json`（guest = 0x10000 + offset）

## 构建命令

```powershell
pwsh -File d3-android/gpu/build_gpu.ps1
cd d3-android
python -I tools/build_host.py --with-gpu --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --output-dir build/host-gpu
python -I tools/build_apk.py --host build/host-gpu/libd3host.so --guest <libd3guest.so> --output-dir build/apk
```
