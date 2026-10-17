# Vulkan图形栈调研结果

## 当前项目状态

- **阶段**: 1.2（越过cmd20，推进到nvdrv ioctl调用）
- **预估工作量**: 
  - Shader重编译器: 150-400h
  - nvdrv翻译: 300-800h
  - Vulkan后端: 200-600h
  - **总计**: 650-1800h

## 关键资源

### 1. Switch模拟器的Vulkan实现

#### Yuzu (归档)
- `video_core/renderer_vulkan/` - 最成熟的实现
- Maxwell GPU命令翻译模式
- 完整的管线状态管理
- **状态**: 代码仍可从归档/fork获取

#### Ryujinx
- `Ryujinx.Graphics.Vulkan/` - C#实现
- 架构更清晰，易于理解
- **用途**: 作为文档参考，不直接移植

#### Skyline
- `app/src/main/cpp/skyline/gpu/` - ARM64 Android原生
- 已为Adreno GPU优化
- **推荐**: 最适合我们的架构

### 2. API翻译层参考

#### DXVK (D3D11 → Vulkan)
- **GitHub**: github.com/doitsujin/dxvk
- **亮点**: 
  - 成熟的命令缓冲区管理
  - 状态跟踪与同步
  - 管线缓存策略
- **许可证**: Zlib (GPL兼容)

#### MoltenVK (Metal → Vulkan)
- **GitHub**: github.com/KhronosGroup/MoltenVK
- **亮点**: 
  - API包装模式
  - 管线状态管理
  - 跨平台抽象
- **许可证**: Apache 2.0 (GPL兼容)

### 3. Vulkan辅助库

#### vk-bootstrap
- **GitHub**: github.com/charles-lunarg/vk-bootstrap
- **功能**: 简化Vulkan初始化（instance/device/swapchain）
- **优势**: 减少~1000行样板代码
- **许可证**: MIT (GPL兼容)
- **推荐**: ✅ 必用

#### Volk
- **功能**: 单头文件Vulkan加载器
- **优势**: 减少链接复杂度
- **许可证**: MIT

### 4. Android/Adreno专用资源

#### Android NDK Vulkan示例
- **GitHub**: github.com/android/ndk-samples
- **内容**: 
  - Android Surface集成
  - Adreno最佳实践
  - 生命周期管理

#### Qualcomm Adreno SDK
- **来源**: Qualcomm Developer Network
- **内容**: 
  - Adreno专用Vulkan扩展
  - 瓦片渲染器性能指南
  - Galaxy Tab S8 (Adreno 730)优化建议

### 5. Maxwell GPU文档

#### envytools
- **网站**: envytools.readthedocs.io
- **内容**: Maxwell架构逆向工程文档
- **覆盖**: 寄存器布局、命令格式

#### Switch Brew Wiki
- **网站**: switchbrew.org/wiki/NV_services
- **内容**: 社区文档化的nvdrv/nvhost协议

---

## 减少工作量的策略

### 方案A: 直接集成Eden（原计划）
```
Eden shader_recompiler (239文件)
  + Eden nvdrv layer (37文件)
  + Eden renderer_vulkan (105文件)
```
- **优势**: 完整、经过验证
- **劣势**: 高度耦合，GPL-3.0（已接受）
- **工作量**: 650-1800h（原估算）

### 方案B: 混合轻量化 ⭐ 推荐
```
Eden shader_recompiler (不可避免，最复杂)
  + 最小nvdrv适配层（参考Ryujinx清晰架构）
  + vk-bootstrap + DXVK模式（而非完整eden后端）
```
- **优势**: 减少耦合，可能省200-400h
- **劣势**: 需要更多架构设计
- **工作量**: 450-1400h（估算）

### 方案C: 先研究后编码 ⭐⭐ 强烈推荐

**在承诺650-1800h之前**:

1. **完成阶段1.2** - 让nvdrv ioctl调用出现在日志中
2. **捕获真实nvdrv流量** - 来自实际D3 guest代码
3. **分析D3使用的Maxwell命令** - 可能只是完整GPU的子集
4. **做出明智决策** - 是否需要全部105个eden后端文件

**关键洞察**: 200-600h的Vulkan后端估算假设需要**完整模拟器功能**。一个兼容层只服务一款游戏，可能只需要**20-30%的功能**，如果只实现D3实际使用的部分。

---

## 实施路径

### 阶段1: 原型验证（推荐先做）
1. 使用vk-bootstrap在Android上渲染一个三角形
2. 验证Surface设置正确
3. 测试Adreno 730的基本功能
4. **工作量**: 8-16h

### 阶段2: nvdrv流量分析
1. 完成当前的cmd20阻塞
2. 推进到nvdrv ioctl调用出现
3. 记录D3实际发起的命令
4. **依赖**: 完成阶段1.2

### 阶段3: 最小可行图形
1. 实现D3使用的nvdrv命令子集
2. 集成Eden shader重编译器
3. 渲染首帧
4. **工作量**: TBD（基于阶段2的分析）

---

## Vulkan栈架构建议

```
D3 Guest Code
     ↓
  NVN API调用
     ↓
/dev/nvhost-gpu ioctl
     ↓
【nvdrv适配层】← 参考Skyline/Ryujinx
     ↓
Maxwell 3D命令
     ↓
【Shader重编译器】← Eden (SASS → SPIR-V)
     ↓
【Vulkan后端】
  ├─ vk-bootstrap (初始化)
  ├─ 管线管理 (参考DXVK)
  ├─ 命令缓冲区 (参考Skyline)
  └─ 同步/提交 (Adreno优化)
     ↓
Android Surface
     ↓
Adreno 730 GPU
```

---

## 需要调研的Eden文件（当获取到时）

```
src/shader_recompiler/      ← SASS→SPIR-V（不可避免）
services/nvdrv/devices/     ← nvhost-gpu、nvmap处理器
video_core/engines/maxwell_3d.* ← GPU状态机
video_core/renderer_vulkan/vk_*.cpp ← Vulkan包装器
```

---

## 关键决策点

### 现在就决定
- ✅ 使用vk-bootstrap（节省大量样板代码）
- ✅ 参考Skyline的Android集成（已验证）
- ✅ 先完成阶段1.2，获取真实nvdrv流量

### 等阶段2完成后决定
- ⏳ Eden完整后端 vs 最小适配层
- ⏳ 需要实现的Maxwell命令范围
- ⏳ 是否需要完整的管线状态模拟

---

## 总结

**不要盲目承诺650-1800h**。先完成阶段1.2，分析D3的实际需求，然后做出明智的技术选择。一个为单款游戏定制的兼容层可能比通用模拟器简单得多。
