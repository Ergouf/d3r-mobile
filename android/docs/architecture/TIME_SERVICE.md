# time:u 与 domain 回复技术说明

> 历史技术说明：整理自 2026-10-16 time 服务接入。本文保留接口与 ABI 注意点，删除旧 cmd20 阻塞状态及逐轮测试副本；当前可玩性见 [STATUS.md](../STATUS.md)，构建见 [BUILD.md](../BUILD.md)。

## 对象与回复

`time:u` 根服务需要分配正确接口类型，由 `port_iface()`、`port_kind()` 与 `domain_command()` 走到对应命令处理器，不能注册为 iface 0 的无效对象。

根命令 3 `GetTimeZoneService` 的两种回复形式：

- domain 会话：分配属于该 session 的 child 对象，回复恰好一个输出 domain 对象；表满返回错误，不伪造对象 ID。
- 非 domain 会话：通过 HIPC handle slot 返回 move session handle，不把句柄作为额外 payload 字。

`reply_prepare()` 的 domain 输出对象数默认 0；只有真正输出对象的回复才设置为 1。CMIF `DomainOutHeader.num_out_objects` 不能因为旧测试 helper 无条件期待 1 就统一改为 1；标量、错误及句柄回复仍应保持正确对象数。

关闭 session 时释放所属的全部 domain 对象；裸 HIPC close 同样需要关闭 handle。不同会话的 child ID 不可互用。

## ABI 定位

日志中某个 `args` 字可能是上次回复残留的 out-object，不一定是当前请求输入。历史 cmd20 曾出现 `args=0xe`，但请求本身只有 CMIF 头而无该输入；应结合 domain `data_size`、CMIF 头和实际 buffer 分析，不能按残留值反推 ABI。

`Break(0)→SIGABRT` 若发生在登记 guest 线程，应与非 guest ART/JIT 线程故障分开定位。tombstone 中看到 host `fail()` 只说明上报路径，不能据此直接判断根因。

## 回归要点与源码

`test_time_service` 检查 root iface、单 child 回复、会话隔离、foreign ID/close 失效、表满失败、未知命令拒绝、非 domain move handle 和 whole-session close。

测试回复 helper 应显式参数化期望对象数，保留业务断言。dump 相关测试需先建立运行时目录，不把环境缺目录归为服务语义错误。

源码入口为 `android/host/d3_service.c`、`d3_service_names.h` 与 `android/tests/test_time_service.c`。同步语义另见 [SYNC.md](SYNC.md)。
