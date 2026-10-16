# Diablo III Switch → Android 原生运行 - 项目路线图

**目标**：让 Switch 版暗黑破坏神 III 在 Android ARM64 设备上**原生执行**（非模拟器），通过兼容层转换 Horizon OS 服务与 NVN 图形到 Android/Vulkan。

**当前状态**：✅ 已达到 `nnMain` 返回，阻塞在 cmd20 `GetSharedMemory` 未实现（ITimeService）

**许可证**：接受 GPL-3.0 以复用 eden-emu 的图形栈

---

## 架构原则

**不是模拟器**：Switch 与 Android 都是 ARM64，guest 代码**原生执行**，只有系统调用与图形 API 需要兼容层转换：

```
Switch Guest (ARM64)
     ↓ 原生执行（同芯片）
     ↓ SVC 拦截
  veneer 桩 → d3_hle_dispatch (host)
     ↓
  转换层：Horizon → Android
     ↓        NVN → Vulkan
  Android 系统 / Vulkan
```

**代码来源**：
- 当前 host（4184 行）：轻量、原生、已验证到 nnMain
- eden-emu：图形栈（shader 重编译器、Maxwell 引擎、Vulkan 后端）
- **不复用**：eden 的内核模拟层（927 文件）——我们已有更轻的替代

---

## 阶段 1：启动路径畅通 ⏳ 进行中

**目标**：推进到出现 nvdrv ioctl 调用（图形初始化）

### 1.1 同步 SVC 原子快路径（B 方案）✅ 已批准
- **WHY**：同芯片应让 ARM64 原子指令直接执行，host 只在真正睡眠/唤醒介入
- **WHAT**：改 veneer 同步桩（0x1A-0x1D），快路径用 guest 自己的 `ldaxr/stlxr`
- **工作量**：8-20 小时
- **成功标准**：8 suite 回归通过、真机验证无新崩溃

### 1.2 越过 cmd20 阻塞
- **当前**：`GetSharedMemory` 返回 `unimplemented` → Break(0x26)
- **WHAT**：实现 ITimeService cmd20 + 相关未实现服务
- **工作量**：10-30 小时（按出现顺序逐个）
- **成功标准**：启动日志出现 `/dev/nvhost-*` ioctl 调用

---

## 阶段 2：图形栈集成 ⏳ 待启动

**前提**：完成阶段 1，有真实 nvdrv 调用日志

### 2.1 着色器重编译器（优先级最高）
- **来源**：eden `src/shader_recompiler/`（239 文件，GPL-3.0）
- **WHY**：guest 着色器是 Maxwell SASS 二进制，必须反编译成 SPIR-V
- **耦合度**：低（依赖 `sirit` + `fmt` + `common`）
- **工作量**：150-400 小时（含适配与验证）

### 2.2 nvdrv ioctl → Vulkan 翻译
- **来源**：参考 eden `services/nvdrv/`（37 文件）+ `video_core/engines/`（22 文件）
- **WHAT**：拦截 `/dev/nvhost-gpu`/`/dev/nvmap` 等，转为 Vulkan 命令
- **耦合度**：中（需适配 Maxwell 3D 状态模型）
- **工作量**：300-800 小时

### 2.3 Vulkan 后端
- **来源**：eden `video_core/renderer_vulkan/`（105 文件）
- **WHAT**：SPIR-V → Vulkan 管线 → Android Surface
- **工作量**：200-600 小时

**阶段 2 总计**：650-1800 小时（取决于可复用程度与遇到的适配问题）

---

## 阶段 3：可玩性优化 ⏳ 待定

- 音频（audout/audin）
- 输入（hid）
- 存档
- 性能优化
- 剩余端口（guest 请求了 218 个，当前实现 26 个）

---

## 关键决策与约束

1. **GPL-3.0 接受** ✅ 已确认——整个 host 必须以 GPL-3.0 发布并开源
2. **不要模拟器** ✅ 已确认——ARM64 原生执行，不引入 eden 的 CPU 模拟层
3. **目标设备**：Galaxy Tab S8（骁龙 8 Gen 1 / Adreno 730 / 8GB）

---

## 文档组织

**必读（开工前）**：
- **ROADMAP.md**（本文）— 总体路线与当前阶段
- **d3-android/GOAL.md** — 已完成工作与剩余任务
- **d3-android/RECOVERY.md** — 最新技术状态与回归
- **HANDOFF.md** — 详细技术规范与调试历史

**阶段性文档**：
- **d3-android/SIGNAL_CHAIN.md** — signal 阶段证据
- **d3-android/TIME_SERVICE.md** — time 阶段证据
- **d3-android/SYNC.md** — sync 阶段证据

**已删除（过时）**：
- ~~BUILD_STATUS.md~~（概念验证版，已被真实 host 取代）
- ~~COMPLETION_REPORT.md~~（TLR 修复版，已被 signal/time/sync 三阶段取代）
- ~~PROJECT_STATUS.md~~（重复，已并入 GOAL/RECOVERY）
- ~~REWRITE_PROGRESS.md~~（未完成的重写尝试，已废弃）

---

## 里程碑验证

### 已达到 ✅
- ✅ Guest 加载并执行到 `nnMain`
- ✅ TPIDRRO 无限循环已修复
- ✅ Break(0x26) 已绕过
- ✅ 日志 SIGSEGV 已修复
- ✅ Signal chain（sigaction hook）已实现并验证
- ✅ Time service（ITimeService cmd3）已实现并验证
- ✅ Sync primitives（SVC 0x1A-0x1D）已实现并回归

### 下一个里程碑 ⏳
- 越过 cmd20，到达 nvdrv 调用（阶段 1.2）
- 首帧渲染成功（阶段 2 完成）
- 可交互游玩（阶段 3 完成）

---

## 维护规则

1. **所有 AI 第一次开工前必须读本文件**，了解当前阶段与目标
2. **阶段切换时更新本文件**，标注新的 ⏳ 进行中
3. **每达到里程碑创建独立证据文档**（如 SIGNAL_CHAIN.md），不在本文件堆积细节
4. **定期同步 GOAL.md 与 RECOVERY.md**，它们是最新技术状态的权威来源

---

**最后更新**：2026-10-16  
**当前阶段**：阶段 1.1（同步 SVC 原子快路径）开始实施
