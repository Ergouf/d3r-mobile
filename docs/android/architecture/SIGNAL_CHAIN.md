# 信号链技术说明

> 历史技术说明：整理自 2026-10-16 信号链实现。这里保留接口原理和测试边界，删除当时的 PID、构建副本和逐轮报告。当前状态见 [STATUS.md](../../STATUS.md)，构建见 [BUILD.md](../BUILD.md)。

## 安装与转交

host 的崩溃信号通过 libc `sigaction` 安装，使 ART signal chain 仍先于用户动作运行。不要用 raw `rt_sigaction` 直接替换内核 handler 作为日常安装方法。

- `install_signal_actions()` 使用 `pthread_once`；此前用户动作只保存一次，保留 `sa_mask`、`SA_RESTART` 与 `SA_NODEFER`。
- `chain_signal()` 处理普通 handler、`SA_SIGINFO`、`SA_RESETHAND` 和 `SIG_IGN`。同步致命故障不能靠忽略后返回循环吞掉。
- 最终默认致命动作通过 raw syscall 恢复 `SIG_DFL`、`tgkill` 重发并解除对应信号阻塞，保留真实信号终止语义，不能改为固定 `exit_group(1)`。
- 非 guest 线程先转交信号链，不触碰 guest tp/x18，也不冒充 guest 写 crash dump；guest 线程记录故障并链式调用此前动作，返回前恢复被打断的 tp/x18。

日志中的 `user/ours/kernel/chained` 用于区分用户动作与内核槽。ART 未 claim 的信号和经 ART 调度的信号可能在同一进程共存，应关联实际线程身份，不能只凭 handler 地址推断。

## 测试边界

`test_signal_chain` 的有效检查包括：此前普通/`SA_SIGINFO` 动作链式一次且能返回、重复安装不重复链接、非 guest 线程保留自己的 tp/x18、guest 线程在登记 host TLS 上执行链式动作并恢复中断上下文、dump 标记正确，以及默认致命动作按真实信号退出。

native fake-TLS 测试不覆盖 ART pre-user pthread 阶段的 TLS 访问；短时间没有复现崩溃也不等于所有 guest/ART 交互风险均已消除。测试夹具必须创建实际使用的 `private/files`、`private/cache` 和 `data/logs`，避免把 dump 路径缺失当作实现回归。

## 源码入口

`d3-android/host/d3_host.c`、`d3-android/tests/test_signal_chain.c`。同步相关约束见 [SYNC.md](SYNC.md)。
