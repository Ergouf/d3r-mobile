# M2/M3 present-path investigation

状态：composite 已提交但屏幕不更新（去掉 M1 clear 时是纯黑帧）。
GPU 线程都在跑：`VulkanWorker`、`VulkanPresent`、`GPUFencingThrea...`。

## 调用链（源码位置）

```
GPU::RequestComposite            video_core/gpu.cpp
  └ ThreadManager::RequestComposite -> GPU 线程命令
      └ RendererVulkan::Composite  video_core/renderer_vulkan/renderer_vulkan.cpp
          ├ render_window.OnFrameDisplayed()          （我们的子类：空实现，可覆盖）
          ├ render_window.IsShown()                    （返回 true）
          ├ present_manager.GetRenderFrame()          （等空闲帧，可能阻塞）
          ├ blit_swapchain.DrawToFrame(...)           （vk_blit_screen.cpp）
          ├ scheduler.Flush(*frame->render_ready)
          └ present_manager.Present(frame)            （vk_present_manager.cpp）
```

`Present()` 在 `use_present_thread` 为真时把 frame 塞进 `present_queue`，
由 `PresentThread` 调 `swapchain.AcquireNextImage / Present`。

## 最可疑的三个点

1. **`GetRenderFrame()` 阻塞**：composite 返回后 GPU 线程可能卡在等空闲帧，
   于是 `DrawToFrame` 从未执行。验证：在 `GetRenderFrame` 前后各打一条日志。
2. **`EmuWindowD3` 的 layout 与 surface 尺寸**：`FramebufferLayout` 是构造时用
   `ANativeWindow_getWidth/Height`（2484x475）算的；若 `blit_swapchain` 期望
   与 swapchain 实际 extent 不一致，可能画到 0 区域。
3. **两个 swapchain 抢同一个 surface**：M1 的 `d3_vk_clear` 和 RendererVulkan
   各建了一个 swapchain。已验证：去掉 clear 后是黑帧，说明 Eden 的
   `Present` 没把图像送到 surface（而不是"被 clear 覆盖"）。

## 下一步（按顺序）

1. 临时给 `vk_present_manager.cpp` 的 `Present` / `PresentThread` 加日志（本地
   vendor 补丁，不提交），确认是否真的调用 `swapchain.Present`、返回值
2. 若 `Present` 未被调用 → 查 `GetRenderFrame` 是否卡住（日志/断点）
3. 若 `Present` 被调用但画面不变 → 查 `swapchain.Create` 的 extent/format 与
   `blit_swapchain` 的 viewport 是否匹配
4. 定位后把临时日志移除，只在我们的 host 层保留开关式日志

## 相关文件

- `d3-android/gpu/host/emu_window_d3.{h,cpp}` —— EmuWindow 子类
- `d3-android/gpu/host/renderer_bringup.cpp` —— 渲染器/composite 测试
- `reference/eden/src/video_core/renderer_vulkan/vk_present_manager.cpp`
- `reference/eden/src/video_core/renderer_vulkan/vk_blit_screen.cpp`
