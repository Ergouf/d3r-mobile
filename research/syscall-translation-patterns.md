# 系统调用转换层调研结果

## 关键参考架构

### 1. FEX-Emu (x86-64→ARM64, 轻量级)
- **特点**: 只转换syscall接口，无CPU模拟
- **模式**: 表驱动的syscall分发器
- **适用**: ARM64原生执行 + syscall拦截（完全匹配我们的需求）

### 2. Wine服务架构
- **特点**: API级转换（Windows→Unix）
- **模式**: 服务对象模型 + IPC marshalling
- **适用**: Horizon服务到Android的映射

### 3. Horizon HLE (Ryujinx/yuzu)
- **协议**: HIPC命令缓冲区，句柄传递
- **关键服务**: nn::os (线程/同步), nn::mem, nn::time
- **参考**: switchbrew.org/wiki/IPC_Marshalling

### 4. Box64 syscall拦截
- **方法**: LD_PRELOAD + signal handler捕获syscall指令
- **优势**: 最小开销，无完整CPU模拟

## 推荐架构映射

```
同步原语映射:
  Horizon Mutex    → pthread_mutex (via futex)
  Horizon CondVar  → pthread_cond (via futex)
  Horizon Semaphore → sem_t / custom futex
  Horizon Event    → eventfd / pipe

服务分发:
  HIPC buffer → 解析命令 → 服务实现 → 编组响应
```

## 关键模式

1. **Syscall表** (FEX风格): handler表 + 参数转换 + 错误码映射
2. **服务注册表** (Wine风格): 惰性初始化 + 句柄生命周期
3. **Futex同步** (Android): ARM64原子指令快路径 + futex慢路径

## 与当前项目的契合度

✅ 我们已有:
- SVC拦截机制 (d3_hle_dispatch)
- 信号链保留 (Android signal chain)
- 同步原语启动子集 (d3_sync: lock/unlock/process-wide-key)

🔄 需要补充:
- 完整的服务分发表
- IPC marshalling层
- 更多Horizon服务实现 (当前只有time:u cmd3)

## 下一步

优先级1: 实现cmd20 GetSharedMemory，参考Ryujinx的ITimeService实现
优先级2: 扩展服务分发表，准备nvdrv等图形相关服务
