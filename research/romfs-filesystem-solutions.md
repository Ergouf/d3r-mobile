# RomFS与文件系统方案

## 当前阻塞

从RECOVERY.md：
> `/sdcard/D3/RomFS` 缺失；图形、音频、输入未实现

这是明确的阻塞点。游戏会尝试`open()`和`read()`系统调用，当前没有处理器。

---

## RomFS实现架构

### 1. Switch RomFS结构

**RomFS特点**：
- 只读内存文件系统
- 包含游戏资源（纹理、模型、音频、脚本等）
- 典型大小：500MB - 3GB

**容器格式**：
- **NCA** (Nintendo Content Archive) - 游戏内容容器
  - 分段：code, data, RomFS, metadata
  - 加密：AES-128-CTR per section
  - 需要解析：magic, section headers, key indices
  
- **NSP** (Nintendo Submission Package) - 可分发包
  - 包装NCA文件的容器
  - 需要提取NCA

### 2. 模拟器实现模式

**分层抽象**（Yuzu/Ryujinx模式）：
```
VirtualFilesystem
    ↓
  挂载点
    ↓
 存储后端（NCA/NSP/目录）
```

**Android推荐**：
- 使用memory-mapped regions访问NCA/NSP
- 挂载到guest虚拟路径`/romfs`
- 避免完整提取（存储限制）

---

## 文件格式工具

### NCA/NSP解析器

**hactool** (C, GPL)
- 完整的NCA/NSP提取参考实现
- 命令行工具，可提取库代码

**nxcli** (Rust, 宽松许可)
- 轻量级解析
- 可编译为C库

**模拟器内置**
- Yuzu/Ryujinx都有自定义解析器
- 可从归档中提取架构参考

---

## 存档加密

### Switch存档格式

**结构**：
```
Header + CMAC (AES-128-CMAC认证标签) + 加密载荷
```

**加密**：
- AES-128-CTR，per-save IV
- 密钥派生：主密钥 + title ID
- **关键**：主密钥是设备特定的

### Android实现策略

**方案A**: 预解密存档（推荐）
- 离线解密Switch存档
- 以明文形式提供给兼容层
- 挂载到`/user`路径

**方案B**: 实时解密
- 实现密钥派生和解密
- 需要设备主密钥
- ⚠️ 法律灰色地带（密钥提取）

**推荐**: 使用方案A，不涉及密钥提取

---

## 虚拟文件系统库

| 库 | 许可证 | 大小 | 特点 |
|----|-------|------|------|
| **PhysFS** | ZLIB | ~100KB | 游戏VFS，支持ZIP/RAR/7z |
| **FUSE** | GPL/LGPL | 中等 | 内核模块，开销过大 |
| **libzip** | BSD | ~200KB | 仅ZIP |

### 推荐：自定义轻量层

**原因**：
- D3特定需求，不需要通用VFS
- guest系统调用→host文件句柄的简单映射
- 延迟加载NCA section按需
- 缓存解压块到内存

**实现**：
- 拦截guest `open()`/`read()`/`close()`
- 映射虚拟路径到NCA内偏移
- 零拷贝或mmap访问

---

## Android存储最佳实践

### Scoped Storage (Android 11+)

**目标**: API 36 (Android 16)强制scoped storage

**推荐目录结构**：
```
/data/user/0/com.d3mobile.host.recovery/
├── files/runtime/      ← RomFS、代码、资源
├── files/savedata/     ← 解密存档
└── cache/              ← 临时解压块
```

**权限需求**：
- `READ_EXTERNAL_STORAGE`（旧版）或`READ_MEDIA_IMAGES`（新版）
- `WRITE_EXTERNAL_STORAGE`（用于`/sdcard/D3/logs`）
- `MANAGE_EXTERNAL_STORAGE`（仅在必要时）

---

## 实施路径

### 阶段1: 静态RomFS挂载 ⭐ 优先

**步骤**：
1. 离线从游戏包提取NCA
2. 挂载RomFS section为只读到guest地址空间
3. 实现SVC处理器：guest文件`open/read`

**工作量**: 40-80小时

**成功标准**: 
- guest能打开`/romfs/data/file.dat`
- 读取返回正确内容
- 不崩溃

---

### 阶段2: 存档处理

**步骤**：
1. 创建guest `/user`目录结构
2. 挂载预提取的明文存档
3. 添加存档持久化到APK包

**工作量**: 30-60小时

---

### 阶段3: 动态文件系统（可选优化）

**步骤**：
1. 延迟加载NCA sections（page fault时）
2. 实现`open()`, `read()`, `lstat()`等完整syscall
3. 缓存高频访问块

**工作量**: 60-120小时

---

## 当前项目中的相关代码

从代码库：
```c
// d3_host.c 行1140-1291: guest ELF加载和内存映射
// 这里可以添加RomFS映射逻辑

// d3_service.c: 服务分发
// 添加文件系统SVC处理器

// 当前存储路径定义 (d3_host.c 行43-46):
// CRASH_PATH, PROBE_INFO_PATH, D3_DATA_ROOT
```

**需要添加**：
```c
// guest_layout.h: 定义RomFS虚拟地址范围
#define ROMFS_BASE 0x????'????'0000  // 待定
#define ROMFS_SIZE 0x?'0000'0000      // 待定

// d3_host.c: RomFS加载函数
void load_romfs(const char* nca_path);

// d3_service.c: 文件系统SVC
uint64_t svc_open_file(const char* path, int flags);
ssize_t svc_read_file(int fd, void* buf, size_t count);
int svc_close_file(int fd);
```

---

## `/sdcard/D3/RomFS`路径解释

**当前错误**: 游戏期望此路径存在

**可能性**：
1. **预提取目录**: 明文RomFS已提取到此路径
2. **NCA文件**: 指向NCA文件的路径
3. **内存镜像**: mmap的RomFS镜像

**推荐调查**：
```bash
# 检查原始APK预期的路径
grep -r "sdcard.*RomFS" d3-android/
grep -r "D3.*RomFS" recovery/
```

---

## 工作量总结

| 阶段 | 描述 | 工作量 |
|------|------|--------|
| 阶段1 | 静态RomFS挂载 + 基础文件SVC | 40-80h |
| 阶段2 | 存档处理 | 30-60h |
| 阶段3 | 动态FS优化（可选） | 60-120h |
| **最小可行** | 仅阶段1 | 40-80h |
| **完整方案** | 阶段1+2 | 70-140h |

---

## 下一步行动

### 立即（阶段1.2后）
1. 定位D3游戏的NCA文件
2. 使用hactool提取RomFS section
3. 确定guest虚拟地址布局
4. 实现最小文件open/read SVC

### 中期（阶段2前）
1. 提取存档（如果需要）
2. 实现完整文件系统syscall集
3. 测试游戏资源加载

### 长期优化
1. 按需加载大文件
2. 内存优化（缓存策略）
3. 性能profiling

---

## 关键依赖

⚠️ **阻塞条件**: 
- Guest线程调度必须实现（当前仍是stub）
- `WaitSynchronization`和events需要完成
- 文件I/O可能涉及异步操作

**建议**: 在完成阶段1.2并推进到图形初始化后，再全力实现文件系统。
