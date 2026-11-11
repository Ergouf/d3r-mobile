# 同步原语技术说明

> 历史技术说明：整理自 2026-10-16 同步模块接入。早期单 guest 上下文、cmd20 阻塞和当时测试结果不代表当前状态；最新结果见 [STATUS.md](../STATUS.md)，构建见 [BUILD.md](../BUILD.md)。

## SVC 接线与语义

`d3_sync.c` / `d3_sync.h` 提供 host 同步原语，使用 pthread 内部锁、条件变量和 FIFO 等待队列，并校验 guest 地址。`d3_host.c` 的 SVC 接线为：

| SVC | 接口 |
| --- | --- |
| `0x1A` ArbitrateLock | `d3_sync_lock`，校验 owner/tag |
| `0x1B` ArbitrateUnlock | `d3_sync_unlock` |
| `0x1C` WaitProcessWideKeyAtomic | `d3_sync_wait`，写 key hint、释放 mutex、执行等待 |
| `0x1D` SignalProcessWideKey | `d3_sync_signal` |

`timeout == 0` 需要返回 `0xea01`，保持 mutex 已释放且不重新获取；不能用空成功 stub 或忙循环替代真实等待。FIFO 子集也不能自动等同于 Horizon 的优先级继承、取消或线程终止语义，后续修改应按实际支持范围测试。

## 回归要点

`test_sync` 覆盖有界等待、零超时、超时语义、signal 竞态、锁交接、地址校验和 SVC ABI。ABI 检查应覆盖：tag 不匹配时不改 word、正确 owner 解锁、`timeout=0` 的返回值与 mutex/key hint 状态、signal 的 key 清零，以及 x1/x2 等非返回寄存器保存。

测试夹具须建立正确 runtime 层级。历史上 dump 检查失败曾由 `private/files` 等目录缺失导致，不应为满足测试修改业务语义。

真实 guest 的 SVC 序列有界，仅说明没有观察到该窗口的忙循环；若 guest 没有行使对应 lock/wait 路径，不能把 native suite 通过写成真实多 guest 线程调度已验收。

## 源码入口

`android/host/d3_sync.c`、`d3_sync.h`、`d3_host.c` 与 `android/tests/test_sync.c`。ART 信号/TLS 的独立风险见 [SIGNAL_CHAIN.md](SIGNAL_CHAIN.md)。
