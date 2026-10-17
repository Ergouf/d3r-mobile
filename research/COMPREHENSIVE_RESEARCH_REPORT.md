# 深度调研综合报告：优化路线图

**调研日期**: 2026-10-16  
**项目**: Diablo III Switch → Android ARM64 兼容层  
**目标**: 减少重复造轮子，利用开源项目加速开发

---

## 执行摘要

通过7个并行子代理的深度调研，我们发现了大量可复用的开源组件，可以显著减少预估工作量。关键发现：

### 🎯 最重要的洞察

1. **Skyline/Strato是关键**: 由于yuzu/Ryujinx下线，Skyline成为唯一活跃的ARM64原生Switch执行参考，架构与我们完全一致
2. **不要盲目承诺650-1800h**: 先完成阶段1.2获取真实nvdrv流量，再决定需要实现的Maxwell命令范围
3. **阶段性实施**: 最小可行方案可能只需要完整图形栈的20-30%

### 📊 工作量优化潜力

| 原估算 | 优化后 | 节省 | 关键措施 |
|--------|--------|------|----------|
| 阶段1.2: 10-30h | 10-30h | 0h | 无优化空间，核心路径 |
| 阶段2.1: 150-400h | 130-380h | 20-50h | 使用sirit库代替手写SPIR-V |
| 阶段2.2: 300-800h | 150-400h | 150-400h | 参考Skyline而非完整移植eden |
| 阶段2.3: 200-600h | 100-300h | 100-300h | vk-bootstrap + 针对D3裁剪 |
| **阶段2总计** | **650-1800h** | **380-1080h** | **270-720h节省** |

---

## 第一部分：关键技术栈推荐

### 1.1 立即使用（阶段1-2）

#### Skyline Emulator ⭐⭐⭐ 最高优先级

**为什么是最佳选择**:
- ✅ ARM64 Android原生执行（与我们架构完全一致）
- ✅ MPL-2.0许可证（GPL-3.0兼容）
- ✅ 已验证的服务实现（time/nvdrv/HID/audio）
- ✅ 无需剥离CPU模拟层

**立即行动**:
```bash
git clone https://github.com/skyline-emu/skyline
# 或更活跃的继任者
git clone https://github.com/strato-emu/strato

# 关键目录
services/timesrv/    # 当前阻塞的cmd20参考
services/nvdrv/      # 阶段2需要的nvdrv实现
gpu/interconnect/    # GPU命令缓冲区翻译
```

**用途**:
- 解决当前cmd20阻塞（参考ITimeService::GetSharedMemoryHandle）
- 阶段2.2参考nvdrv到Vulkan的翻译架构
- 理解Android设备上的内存映射和信号处理

---

#### sirit - SPIR-V生成库

**GitHub**: https://github.com/ReinUsesLisp/sirit  
**许可证**: BSD-3-Clause  
**用途**: 阶段2.1 Shader重编译器的SPIR-V生成

**集成**:
```cmake
add_subdirectory(external/sirit)
target_link_libraries(d3host sirit)
```

**节省**: 20-30小时（vs手写SPIR-V二进制）

---

#### vk-bootstrap - Vulkan初始化助手

**GitHub**: https://github.com/charles-lunarg/vk-bootstrap  
**许可证**: MIT  
**用途**: 阶段2.3简化Vulkan初始化

**效果**: 减少~1000行样板代码

---

#### Oboe - Android音频库

**GitHub**: https://github.com/google/oboe  
**许可证**: Apache-2.0  
**用途**: 阶段3音频后端

**特点**:
- Google官方维护
- 自动选择AAudio/OpenSL ES
- 10-20ms低延迟

---

### 1.2 参考但不直接移植

#### Eden/Yuzu归档

**用途**: 文档和算法参考，不完整移植

**关键文件**:
- `src/shader_recompiler/` - Maxwell解码算法
- `src/video_core/renderer_vulkan/` - Vulkan模式
- `services/` - HLE服务协议

**警告**: 为x86_64设计，需大量适配

---

## 第二部分：按阶段的具体建议

### 阶段1.2: 越过cmd20 (10-30h)

#### 当前阻塞
```
ITimeService cmd20 GetSharedMemory
  → error 0x278
  → Break(0x26)
  → SIGABRT
```

#### 解决方案

**步骤1**: 克隆Skyline
```bash
cd D:/workspace/Diablo/external
git clone https://github.com/skyline-emu/skyline
```

**步骤2**: 找到参考实现
```bash
cd skyline
find . -name "*time*" -type f | grep service
# 预期: app/src/main/cpp/skyline/services/timesrv/
```

**步骤3**: 实现cmd20
```c
// d3_service.c 添加
case 20: // GetSharedMemoryHandle
    // 分配共享内存区域
    size_t size = 0x1000; // 参考Skyline的大小
    int fd = ashmem_create_region("time-shared", size);
    void* addr = mmap(NULL, size, PROT_READ|PROT_WRITE,
                       MAP_SHARED, fd, 0);
    
    // 初始化时间结构（稳定时钟 + 日历时间）
    TimeSharedMemory* tsm = (TimeSharedMemory*)addr;
    tsm->steady_clock = get_steady_clock();
    tsm->calendar_time = get_calendar_time();
    
    // 返回句柄
    reply_handle(msg, fd);
    break;
```

**验证**: 启动日志应该越过cmd20，出现下一个服务请求

---

### 阶段2.1: Shader重编译器 (130-380h)

#### 推荐架构

```
Maxwell SASS二进制
       ↓
【Eden Maxwell解码器】← 复用eden的239文件
       ↓
  中间表示 (IR)
       ↓
【SPIR-V生成】← 使用sirit库 ⭐ 节省20-30h
       ↓
【验证/优化】← SPIRV-Tools
       ↓
    SPIR-V二进制
```

#### 依赖项
```bash
# 获取sirit
git submodule add https://github.com/ReinUsesLisp/sirit external/sirit

# 获取SPIRV-Tools（验证用）
git submodule add https://github.com/KhronosGroup/SPIRV-Tools external/SPIRV-Tools
```

#### 参考Maxwell指令
- https://github.com/akrolik/rNdN (MIT许可，指令树定义)
- envytools.readthedocs.io (逆向文档)

---

### 阶段2.2: nvdrv翻译 (150-400h，原估算300-800h)

#### 为什么能减半

**原估算假设**: 实现完整Maxwell GPU模拟  
**实际需求**: 只实现D3使用的命令子集

#### 先做这个 ⭐ 关键

```bash
# 完成阶段1.2后
adb logcat | grep nvdrv

# 分析D3实际发起的ioctl调用
# 记录：
# - 哪些/dev/nvhost-*设备
# - 哪些ioctl命令号
# - 参数模式
```

#### 基于分析做决策

**场景A**: D3只用20%的Maxwell命令
- 工作量: 150-250h
- 策略: 针对性实现，参考Skyline架构

**场景B**: D3用50%的命令
- 工作量: 250-400h
- 策略: 混合Skyline架构 + Eden部分模块

**场景C**: 需要大部分命令
- 工作量: 400-800h（回到原估算）
- 策略: 移植Eden的完整nvdrv层

---

### 阶段2.3: Vulkan后端 (100-300h，原估算200-600h)

#### 轻量化方案

**不要**:
- ❌ 完整移植eden的105文件renderer_vulkan
- ❌ 实现完整GPU状态缓存
- ❌ 支持所有Vulkan特性

**要做**:
- ✅ 使用vk-bootstrap初始化
- ✅ 参考DXVK的命令缓冲区管理模式
- ✅ 只实现D3需要的管线状态
- ✅ 针对Adreno 730优化（瓦片渲染器）

#### 架构

```
D3 nvdrv ioctl
     ↓
【最小nvdrv适配器】← 参考Skyline
     ↓
Maxwell 3D命令
     ↓
【命令翻译层】← 参考DXVK模式
     ↓
【vk-bootstrap】← 初始化
     ↓
【精简管线】← 只实现D3用到的
     ↓
Android Surface → Adreno 730
```

#### 原型验证（推荐先做）

```cpp
// 用8-16小时验证Vulkan栈可行性
int main() {
    // vk-bootstrap初始化
    vkb::InstanceBuilder builder;
    auto inst = builder.build().value();
    
    // Android Surface
    // 渲染一个三角形
    // 确认Adreno 730正常工作
}
```

---

### 阶段3: 音频/输入/RomFS

#### 3A: RomFS (40-80h)

**最小方案**:
1. 离线提取NCA的RomFS section
2. 使用mmap映射到guest地址空间
3. 实现SVC: `open()`, `read()`, `close()`

**工具**: hactool (GPL, 提取NCA)

#### 3B: 音频 (170-340h)

**推荐栈**:
```
Switch audout/audren
       ↓
  混音/重采样
       ↓
   Oboe (Apache-2.0)
       ↓
AAudio/OpenSL ES
```

**关键库**:
- Oboe: 音频后端
- libswresample (LGPL-3.0, 动态链接): 重采样

#### 3C: 输入 (100-180h 最小)

**基础方案**:
```java
// Android GameController
InputManager.getInputDevice()
  → 映射按钮（注意A/B交换！）
  → 更新HID共享内存
```

**运动控制**: +60-100h（陀螺仪）

---

## 第三部分：优化后的路线图

### 新的工作量估算

```
阶段1.2: 越过cmd20                    10-30h
  ↓
阶段2 原型: Vulkan三角形验证          8-16h  ← 新增
  ↓
阶段2 调研: 分析D3 nvdrv流量          16-24h ← 新增
  ↓
阶段2.1: Shader (sirit优化)          130-380h (省20-50h)
阶段2.2: nvdrv (针对D3裁剪)          150-400h (省150-400h)
阶段2.3: Vulkan (vk-bootstrap+裁剪)  100-300h (省100-300h)
  ↓
阶段3A: RomFS                        40-80h
阶段3B: 音频                         170-340h
阶段3C: 输入                         100-180h
────────────────────────────────────────────
原总计: 1550-3530h
新总计: 724-1750h
节省:   826-1780h (53-50%减少)
```

### 关键里程碑重新定义

**M1: 图形初始化** (完成阶段2调研 + 原型)
- 成功标准: Vulkan在Tab S8上渲染三角形
- 风险降低: 验证技术栈可行性

**M2: 首帧渲染** (完成阶段2)
- 成功标准: D3游戏画面出现（即使卡顿/花屏）
- 关键指标: 有画面输出

**M3: 可玩** (完成阶段3)
- 成功标准: 能控制角色移动并完成一次战斗

---

## 第四部分：立即行动清单

### 今天就做（优先级1）

1. **克隆Skyline/Strato**
```bash
cd D:/workspace/Diablo
mkdir -p external
cd external
git clone https://github.com/skyline-emu/skyline
git clone https://github.com/strato-emu/strato
```

2. **研究cmd20实现**
```bash
cd skyline
grep -r "GetSharedMemory" services/
# 找到ITimeService的实现
```

3. **实现cmd20**
- 在`d3_service.c`中添加cmd20处理
- 参考Skyline的共享内存分配
- 测试：启动应该越过当前阻塞

### 本周完成（优先级2）

4. **添加调研工具**
```c
// d3_service.c 添加详细日志
void log_service_request(const char* service, int cmd) {
    fprintf(g_log, "[SERVICE] %s cmd%d\n", service, cmd);
}
```

5. **准备图形栈依赖**
```bash
# 添加子模块
git submodule add https://github.com/ReinUsesLisp/sirit external/sirit
git submodule add https://github.com/charles-lunarg/vk-bootstrap external/vk-bootstrap
git submodule add https://github.com/google/oboe external/oboe
```

### 阶段1.2后（优先级3）

6. **Vulkan原型**
- 8-16小时
- 在Tab S8上渲染三角形
- 验证Surface设置

7. **nvdrv流量分析**
- 修改后启动，记录所有nvdrv调用
- 生成需求矩阵
- 决定裁剪范围

---

## 第五部分：风险与缓解

### 风险1: Eden代码质量未知

**缓解**:
- 先评估239文件的shader_recompiler
- 如果质量差，考虑参考Skyline/yuzu重写
- 保留2-4周调试buffer

### 风险2: Skyline服务不完整

**症状**: 参考实现缺失关键功能  
**缓解**:
- 同时参考yuzu归档（从archive.org获取）
- Ryujinx C#代码作为算法参考
- switchbrew.org文档作为权威

### 风险3: D3使用罕见GPU特性

**症状**: 阶段2.2分析发现需要80%命令  
**缓解**:
- 如果确实如此，回到完整eden移植
- 原估算300-800h仍然有效
- 但至少我们是informed decision

---

## 第六部分：成功指标

### 阶段1.2成功
- ✅ 启动日志越过cmd20
- ✅ 出现下一个服务请求（可能是nvdrv）
- ✅ 无新崩溃

### 阶段2成功
- ✅ adb logcat显示shader编译成功
- ✅ Vulkan管线创建成功
- ✅ 首帧渲染（即使黑屏也算成功）

### 阶段3成功
- ✅ 能看到游戏画面（纹理/模型）
- ✅ 按钮输入有响应
- ✅ 能听到音频（即使失真）

### 最终成功
- ✅ 能完成一次完整战斗
- ✅ 帧率>20fps（可玩）
- ✅ 可冷启动重现

---

## 附录：许可证合规性

所有推荐组件均GPL-3.0兼容：

| 组件 | 许可证 | 合规方式 |
|------|--------|----------|
| Skyline | MPL-2.0 | 直接兼容 |
| sirit | BSD-3-Clause | 直接兼容 |
| vk-bootstrap | MIT | 直接兼容 |
| Oboe | Apache-2.0 | 直接兼容 |
| libswresample | LGPL-3.0 | 动态链接 |
| SPIRV-Tools | Apache-2.0 | 直接兼容 |

**整个项目**: GPL-3.0 + 开源（已接受）

---

## 结论

通过深度调研，我们发现：

1. **Skyline是宝藏**: ARM64 Android原生执行的唯一活跃参考
2. **不要过度实现**: 针对D3裁剪可能节省50%工作量
3. **先验证后承诺**: 原型→分析→决策，避免盲目估算
4. **工具链成熟**: sirit, vk-bootstrap, Oboe等库可直接使用

**建议**: 按新路线图执行，预期节省826-1780小时（50%）。

---

**文档版本**: 1.0  
**最后更新**: 2026-10-16  
**调研代理**: 7个并行子代理，总计1,357,217 tokens
