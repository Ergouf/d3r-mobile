# Switch模拟器项目分析

## 重要发现：Yuzu和Ryujinx已下线

2024年初，主流Switch模拟器（yuzu、Ryujinx）的GitHub仓库因法律问题已被移除。这使得**Skyline/Strato成为ARM64原生执行的关键参考**。

## 1. Skyline Emulator ⭐ 最适合我们的项目

**GitHub**: https://github.com/skyline-emu/skyline  
**许可证**: MPL-2.0 (Mozilla Public License) - ✅ GPL-3.0兼容  
**平台**: Android ARM64原生执行（完全匹配我们的需求）

### 关键特性
- ✅ **无CPU模拟** - 直接在ARM64上运行Switch代码
- ✅ **专为Android设计** - 不需要跨平台适配
- ✅ **HLE服务实现** - 已有time/HID/nvdrv/audio/fs

### 可复用组件

```
app/src/main/cpp/skyline/
├── services/           ← Horizon OS服务实现
│   ├── timesrv/       ← ITimeService（我们当前阻塞的cmd20可参考）
│   ├── hid/           ← 输入服务
│   ├── nvdrv/         ← NVIDIA驱动（阶段2需要）
│   ├── audio/         ← 音频服务
│   └── fssrv/         ← 文件系统
├── gpu/               ← Maxwell GPU命令处理
│   ├── interconnect/  ← 命令缓冲区翻译
│   └── ...            ← Vulkan后端
└── kernel/            ← IPC、内存、线程同步
```

### 集成成本
- **复杂度**: 低到中等
- **优势**: 架构干净，模块化设计
- **劣势**: 项目似乎停止活跃开发，部分服务可能不完整

### 推荐用途
- ✅ 参考ITimeService的cmd20实现
- ✅ 学习nvdrv到Vulkan的翻译架构
- ✅ 复用GPU命令缓冲区处理逻辑

---

## 2. Strato (Skyline的继任者)

**GitHub**: https://github.com/strato-emu/strato  
**许可证**: MPL-2.0 - ✅ GPL-3.0兼容  
**状态**: Skyline的延续，可能有更新的服务实现

### 优势
- 更活跃的维护
- 修复了Skyline的已知问题
- 同样是ARM64 Android原生

---

## 3. Yuzu (历史归档)

**原GitHub**: yuzu-emu/yuzu（已移除）  
**许可证**: GPL-2.0-or-later - ✅ GPL-3.0兼容  
**平台**: x86_64 + CPU模拟

### 可复用组件（需从归档获取）

```
src/core/hle/service/
├── time/              ← 时间服务参考实现
├── nvdrv/             ← NVIDIA驱动接口
├── hid/               ← 控制器输入
├── audio/             ← 音频输出
├── am/                ← 应用管理器
└── vi/                ← 显示服务

src/video_core/
├── shader/            ← Maxwell着色器反编译器
├── renderer_vulkan/   ← Vulkan后端（105文件）
├── gpu.cpp            ← GPU命令处理器
└── memory_manager.cpp ← GPU内存管理
```

### 集成成本
- **复杂度**: 高
- **原因**: 为x86_64设计，需大量适配到ARM64
- **代码库**: 大型复杂，但文档齐全

### 推荐用途
- ✅ 作为文档和参考（不直接复用代码）
- ✅ 着色器编译器算法（最成熟的实现）

---

## 4. Ryujinx (历史归档)

**原GitHub**: Ryujinx/Ryujinx（已移除）  
**许可证**: MIT - ✅ GPL-3.0兼容  
**平台**: 多平台（C#/.NET）

### 可复用组件

```
Ryujinx.HLE/HOS/Services/  ← 服务实现（文档化良好）
Ryujinx.Graphics.Gpu/      ← Maxwell GPU模拟
```

### 集成成本
- **复杂度**: 极高
- **原因**: C#实现，需完全重写为C/C++
- **优势**: 架构清晰，易于理解

### 推荐用途
- ✅ 仅作为架构参考和文档
- ✅ 理解服务协议和IPC流程

---

## 针对当前阻塞的建议

### 问题：ITimeService cmd20 GetSharedMemory未实现

**立即行动**:
1. 克隆Skyline/Strato仓库
2. 查看`services/timesrv/`目录
3. 找到cmd20的实现：
   - 分配共享内存区域
   - 映射到guest进程地址空间
   - 初始化时间结构（稳定时钟、日历时间）

**参考路径**:
```bash
git clone https://github.com/skyline-emu/skyline
# 或
git clone https://github.com/strato-emu/strato

# 查找时间服务实现
find . -name "*time*" -type f | grep -i service
```

---

## 阶段2图形栈建议

### Shader重编译器（150-400h）
- **首选**: 使用yuzu归档的shader编译器（最成熟）
- **备选**: Skyline的实现（更轻量但可能不完整）

### nvdrv翻译（300-800h）
- **首选**: 参考Skyline的nvdrv实现（已为Android优化）
- **补充**: 参考yuzu的文档和测试用例

### Vulkan后端（200-600h）
- **混合方案**:
  - 使用vk-bootstrap简化初始化
  - 参考Skyline的命令缓冲区管理
  - 学习DXVK的状态跟踪模式
  - 针对D3的实际需求裁剪（不需要完整GPU模拟）

---

## 许可证兼容性总结

| 项目 | 许可证 | GPL-3.0兼容 |
|------|--------|-------------|
| Skyline | MPL-2.0 | ✅ 是 |
| Strato | MPL-2.0 | ✅ 是 |
| Yuzu归档 | GPL-2.0+ | ✅ 是 |
| Ryujinx归档 | MIT | ✅ 是 |

所有项目都可以集成到GPL-3.0项目中。

---

## 关键洞察

由于yuzu和Ryujinx下线，**Skyline/Strato成为ARM64原生Switch执行的唯一活跃参考**。这对我们是好消息，因为：

1. 架构与我们的目标完全一致（ARM64 Android原生）
2. 不需要剥离CPU模拟层
3. 已经过Android设备验证
4. 可以直接学习它们如何处理信号、内存映射等

**建议联系Skyline前开发者**获取架构指导。
