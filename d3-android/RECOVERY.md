# D3HOST 源码恢复检查点

日期：2026-10-16
分支：`recovery/d3host-sources`　代码检查点 `325fcdd`（2026-10-16；更早检查点打标签 `recovered-original-sources-20261016` = `3e1c61c`，无远程仓库）

## 目标

主目标是专用兼容层 + APK 包装，让游戏在 Android 上通过翻译层运行；**不是**还原游戏自身的 C++。

## 已核实的恢复结果

- 从平板 `R52T90127WT` 已安装的 `com.d3mobile.host` 原样提取 APK。
- APK SHA-256：`1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`，与设备端一致。
- APK 内原生库：`libd3host.so`（103,768 字节）、`libd3guest.so`（33,227,200 字节）。
- 从 Claude 文件历史恢复了完整 C 源码，而不是从 APK 反编译得到 C 源码。
- 正确源码集为 `host/d3_host.c`、`host/d3_service.c`、`host/d3_jni.c`；缺失头文件依据 C 源码、guestbridge 及二进制重建。
- 编辑前完整快照（`d3_host.c` 2,260 行、`d3_service.c` 1,100 行）作为存档；这些行数只描述存档，不代表当前工作源码。
- 替换前的简化存根（`*_minimal.c`、`*_new.*`、`d3_table.c` 等）另存于本地恢复目录，不属于正确源码集。

## 文件位置

- 原始 APK：`../recovery/d3host-20261016-huRwPN/apk/base.apk`
- 解压文件：`../recovery/d3host-20261016-huRwPN/extracted/`
- 完整源码快照及哈希/来源：`../recovery/d3host-20261016-huRwPN/source-candidates/`
- 静态分析与原始设备崩溃日志：`../recovery/d3host-20261016-huRwPN/analysis/`

源码快照纳入 Git；APK、原始二进制、内存转储及密钥不纳入 Git，仍保留在本机。

## 构建结果

- `build.sh` 已安全替换为 Python 3.12 绝对路径 wrapper：以 `-I` 启动真实解释器，设置 `MSYS2_ARG_CONV_EXCL=*` 防止 Android 路径被转换为 Windows 路径，且不再拷贝旧头文件。
- `tools/build_host.py` 支持 `--ndk`、`--output-dir`、`--sandbox-root`、`--build-probe`、`--build-tests`；NDK 与输出目录用 Windows 路径，sandbox 用 Android 绝对路径。
- `Makefile` 已改为 `build.sh` 的薄 wrapper，但本机没有 `make`，未执行；请直接用 `build.sh`。
- 严格编译通过：`-Werror --no-undefined -ffixed-x18 -fno-stack-protector`（含 `--build-probe --build-tests`）。
- 初次恢复基线宿主大小 346,288 字节（沙箱路径改写前）；**这是历史基线大小，不是当前产物**，勿当作现在的大小。

## 已验证检查点（代码检查点 325fcdd，2026-10-16，勿当作“永远最新”）

- `c25ab68`：补齐 JNI / 构建输入；GetInfo 14/15 返回完整 1 GiB 栈分配区（而非仅占用的 8 MiB 主栈），`MapMemory`/`UnmapMemory` 转移真实 backing 并保护源区；初始 focus 15 已送达。
- `9fa57f9`：`ISelfController` 命令 16（`SetOutOfFocusSuspendingEnabled`）按 per-object 状态跟踪并对 bool 低字节规范化。
- `3d5d416`：domain 转换改为返回分配的 root，而非硬编码 object 1。防丢失检查：对恰好 `3d5d416` 做干净 `git archive` 后严格构建 4 个产物（`libd3host.so`、`d3_probe`、`test_stack_memory`、`test_applet_focus`）全部通过，无缺失输入。仅验证构建输入完整性，与游戏运行无关。
- `3d9dfe3`：实现 pctl 家长控制 factory 命令 0/1 与 child Initialize 生命周期。
- `c95cac0`：不再 join 已 detach 的 guest 启动线程（移除非法 `pthread_join`）。
- `0f973c2`：前阶段 close checkpoint，解析不带 CMIF payload（无 SFCI magic）的 domain-close 请求；只有真正 HIPC close 2/0 且空 payload 才成功。
- `325fcdd`：本代码检查点，定位 CMIF frame 前先统计 HIPC 描述符（X/A/B/W），校验 raw/domain 数据大小边界，移除全 buffer SFCI 扫描。

## 当前状态（代码检查点 325fcdd）

- 严格构建五产物全部通过。
- 三个 Android 本机 suite 真机全部 PASS：`test_stack_memory`、`test_applet_focus`、`test_hipc_message`（新增，已纳入 build driver）。test helper 亦已修复：`CHECK` 结果需传播至 `main`，frame 显式 16B 对齐；修复后再次真机 PASS。
- 9 个 Python 提取测试 PASS（源未变）。
- 头文件已重建并做局部 ABI 验证；这不等于对所有运行路径的完整验证。
- 对 `325fcdd` 做干净 `git archive`，默认 5 产物严格构建和 9 项 Python 测试均通过。仅证明已跟踪输入完整；未在设备执行此归档构建，也不证明游戏可玩。

## 尚未证明（勿读作“可运行”）

- 游戏不可运行，无 gameMainLoop 证据。
- 隔离 `boot-descriptor-02` probe 能加载、异步 start 返回 0，但 guest 进程最终因断言退出（exit 1），**不是** 20 秒 timeout：走到 `back nninitStartup` 与两个 `DT_INIT`（含 `main`），servicefileclose 对象 14/13 成功，pctl Initialize object 12 ready；随后发起 magic `+0x20` 正确的 plain `set` cmd5，被当作 unimplemented set cmd5 处理（**不再**误判为 domain 28）。
- 当前阻塞为 `set` 命令 5（`GetAvailableLanguageCodes2`）功能未实现，**不是** descriptor parser 问题。
- guest 线程 Create/Start 仍只分配 handle / 返回成功 stub，未实现真正的 guest 线程调度。
- `/sdcard/D3/RomFS` 缺失；graphics/audio/input 与 APK 部署未完成。
- 严格构建与 native 测试都不等于 gameplay，不能让游戏跑起来。

## 工具范围

`build.sh` / `tools/build_host.py` 目前只做编译与设备端 native probe/test 构建；不安装、也不替换设备上已安装的 APK，不选择存根源码，不拷贝旧头文件。

## 设备加载与启动测试

隔离测试目录：`/data/local/tmp/d3host-recovery-huRwPN`。

- 加载旧 APK 宿主：退出码 3，缺少 `g_table`。
- 加载恢复宿主：`RTLD_NOW` + `d3_host_start` 退出码 0。
- 线程栈根因已修正，Android 本机 `test_stack_memory` PASS（含 32 次往返与边界拒绝）；`test_applet_focus` PASS；`test_hipc_message` PASS。
- 最新隔离 boot（`boot-descriptor-02`）：probe 加载、异步 start 返回 0，进程最终断言退出 1（非 timeout），阻塞在未实现的 `set` cmd5。

## 此检查点的限制

仅确认源码已完整救回、可严格构建、可被加载、线程栈与 applet focus/per-object 策略已修正、pctl factory/lifecycle 已建模、HIPC 描述符计数与 raw/domain 边界校验已实现，并自带回归测试；头文件已重建并局部 ABI 验证，运行验证尚未完成。
游戏仍不可运行：`/sdcard/D3/RomFS` 缺失，boot 在 `main DT_INIT` 中因未实现的 `set` cmd5 相关断言退出（见上文“尚未证明”）。
不要将历史文档中的“4/5 问题解决”或“编译成功”理解为游戏可运行。

历史 HANDOFF 中关于 IPC 参数、修改 `x30` 以推进 PC、断言后跳转和崩溃栈回溯的结论需要重新验证：

- 原始 host 的 `g_table` 是指针且为 `static`，不是可供别的文件直接 `extern` 引用的全局数组。
- 原始桥接帧大小是 `0x180`，包含 `x[31]`、NZCV 和 `q0..q7`；不能使用存根的 `x[31] + pc + pstate` 布局。
- 桥接调用签名是 `d3_hle_dispatch(kind, extra, saved)`。
- MRS 使用分支/续接跳板；`x30` 是 LR，不能无条件加 4 当作 PC。
- 原始 SVC `0x21` 用 `x0` 作句柄、TLR 作消息缓冲区；SVC `0x22` 的 `x0` 是用户缓冲区地址，不能凭低地址崩溃推断它是 TLR 偏移。

后续以实际源码、ARM64 反汇编和设备测试结果为准。不会为了复现旧文档的行号或文件大小而填充代码。

## 防丢失约定

每个可恢复里程碑建立一个本地 Git 提交；阶段性提交明确写出尚未通过的验证。
不自动删除未跟踪源码，不把构建成功等同于运行成功。
当前没有配置远程仓库，因此本地 Git 不能防止整个磁盘损坏；配置远程需另行指定目的地址。
