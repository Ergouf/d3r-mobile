# D3HOST 源码恢复检查点

日期：2026-10-16
分支：`recovery/d3host-sources`　代码阶段 `3595280`（2026-10-16；此前 `ab074d3` 为 set 服务，更早检查点打标签 `recovered-original-sources-20261016` = `3e1c61c`，无远程仓库）

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
- `tools/build_host.py` 支持 `--ndk`、`--output-dir`、`--sandbox-root`、`--data-root`、`--private-root`、`--build-probe`、`--build-tests`；NDK 与输出目录用 Windows 路径，sandbox 用 Android 绝对路径；`--sandbox-root` 与 `--data-root`/`--private-root` 互斥。
- `Makefile` 已改为 `build.sh` 的薄 wrapper，但本机没有 `make`，未执行；请直接用 `build.sh`。
- 严格编译通过：`-Werror --no-undefined -ffixed-x18 -fno-stack-protector`（含 `--build-probe --build-tests`）。
- 初次恢复基线宿主大小 346,288 字节（沙箱路径改写前）；**这是历史基线大小，不是当前产物**，勿当作现在的大小。

## 已验证检查点（代码阶段 3595280，2026-10-16，勿当作“永远最新”）

- `ab074d3`：set 服务（HOS 设置）的现代 cmd5（`GetAvailableLanguageCodes2`）经 bounded HIPC buffer 返回 18 个语言码（`en-US` 在 index 1），带完整 22-bit address-high / 36-bit size 字段，用 bounded `process_vm_writev` self-copy 写入，合法 4 字节、byte-aligned 输出可用；旧 cmd1 `OutPointer` 仍 unsupported（**不能说 0..6 全完成**）。
- `3595280`：独立恢复 APK 诊断 shell（`com.d3mobile.host.recovery`）。
- `325fcdd`：定位 CMIF frame 前先统计 HIPC 描述符（X/A/B/W），校验 raw/domain 数据大小边界，移除全 buffer SFCI 扫描。
- `0f973c2`：解析不带 CMIF payload（无 SFCI magic）的 domain-close 请求；只有真正 HIPC close 2/0 且空 payload 才成功。
- `c95cac0` / `3d9dfe3`：不再 join 已 detach 的 guest 启动线程（移除非法 `pthread_join`）；实现 pctl 家长控制 factory 命令 0/1 与 child Initialize 生命周期。
- `c25ab68` / `9fa57f9` / `3d5d416`：补齐 JNI/构建输入，GetInfo 14/15 返回完整 1 GiB 栈分配区并转移真实 backing；`ISelfController` cmd16 按 per-object 跟踪；domain 转换返回分配的 root。
- 防丢失检查（`3d5d416`，仅验证构建输入完整性）：干净 `git archive` 后严格构建无缺失输入。

## 当前状态（代码阶段 3595280）

- 严格 NDK 构建 6 个产物全部通过：`libd3host.so`、`d3_probe` 与 4 个 native test。
- 4 个 Android 本机 suite 真机全部 PASS：`test_stack_memory`、`test_applet_focus`、`test_hipc_message`、`test_set_service`（新增，已纳入 build driver）。test helper 亦已修复：`CHECK` 结果传播至 `main`，frame 显式 16B 对齐。
- 9 个 Python 提取测试 PASS（源未变）。
- 头文件已重建并做局部 ABI 验证；这不等于对所有运行路径的完整验证。
- 对 `3595280` 做干净 `git archive`，6 个 native 产物严格构建、9 项 Python 测试均通过，并用外部保存的 guest 与既有 debug key 打包签名 APK（`apksigner verify` PASS）。**仅证明已跟踪源码/打包输入完整**；未在设备执行此归档产物，`libd3guest.so` 与 key 本就不入 Git。

## 尚未证明（勿读作“可运行”）

- 游戏不可运行，无 gameMainLoop 证据。
- 隔离 `boot-descriptor-02` probe 能加载、异步 start 返回 0，但 guest 进程最终因断言退出（exit 1），**不是** 20 秒 timeout：走到 `back nninitStartup` 与两个 `DT_INIT`（含 `main`），servicefileclose 对象 14/13 成功，pctl Initialize object 12 ready。
- 最新真实 app 启动（`apk-recovery-02-pid27088.log`）：main init array（count 360）执行到索引 160 时 guest SIGSEGV at `sdk+0x4db690`（strcmp），caller `main+0x1a26b74`（`x1=-0x48`）；疑似点是 `ItemLockCooldownMinutes` 注册循环链表 `next` 为 0，**根因仍在分析，不断言是 TLS 或 missing RomFS**。
- 未进入 `nnMain` / game loop；真正 guest 线程调度仍未完成（Create/Start 仍只分配 handle / 返回成功 stub）。
- `/sdcard/D3/RomFS` 缺失；graphics/audio/input 与可玩版本的 APK 部署未完成。
- 严格构建与 native 测试都不等于 gameplay，不能让游戏跑起来。

## 恢复 APK 诊断 shell（包名 `com.d3mobile.host.recovery`）

- 固定包名，与原 `com.d3mobile.host` 分离，**不覆盖**原 APK（原 APK SHA-256 保持 `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`）；原包自身的 `g_table` 闪退仍是独立未决问题，**勿与新包混同**。
- 真机平板 `R52T90127WT` 已安装（UID 10272），由 Activity 启动并手动按钮 tap；新宿主库 `System.loadLibrary` 成功加载，guest 33,227,200 bytes 来自原 APK。
- 内部 root `/data/user/0/com.d3mobile.host.recovery/files/runtime`；private root `/data/user/0/com.d3mobile.host.recovery`；`build_host.py` 已支持 `--data-root`/`--private-root`，与 `--sandbox-root` 互斥。
- 诊断 UI 已在 Android 16（target 36）修 NoActionBar + WindowInsets + dark status icons；截图 `../recovery/d3host-20261016-huRwPN/analysis/apk-recovery-ui-03.png`。默认不 autostart，按钮一次；`Intent autostart=true` 可测试。
- 有 UI 不代表游戏画面可用：启动 guest 后进程仍退出，**不能说不闪退了**。证据日志（ignored）`analysis/apk-recovery-02-pid27088.log`、`apk-recovery-02-service.log`、`apk-recovery-manualtap-01*.log`。

## 离线打包

- `tools/build_apk.py` 用新构建的 host 与保存的 guest 打包并签名 debug APK，`--host`/`--guest` 均为必需输入，不 glob “最新” `.so`；`--keystore` 复用既有本地调试 keystore（不入 Git），换输出目录也复用以避免 UPDATE_INCOMPATIBLE。
- 已验证流程（相对 repo 根，固定包名防覆盖）：

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/set-03 --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --build-probe --build-tests
```

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py --host d3-android/build/set-03/libd3host.so --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --keystore d3-android/build/apk-recovery-set02/local-debug.keystore --output-dir d3-android/build/apk-recovery-set04
```

## 工具范围

`build.sh` / `tools/build_host.py` / `tools/build_apk.py` 只做编译、设备端 native probe/test 构建与离线打包；不安装、也不替换设备上已安装的 APK（实际 `adb install -r` 在用户授权的真机验证中单独执行），不选择存根源码，不拷贝旧头文件。

## 设备加载与启动测试

隔离测试目录：`/data/local/tmp/d3host-recovery-huRwPN`。

- 加载旧 APK 宿主：退出码 3，缺少 `g_table`。
- 加载恢复宿主：`RTLD_NOW` + `d3_host_start` 退出码 0。
- 线程栈根因已修正，Android 本机 `test_stack_memory` PASS（含 32 次往返与边界拒绝）；`test_applet_focus` PASS；`test_hipc_message` PASS；`test_set_service` PASS。
- 最新隔离 boot（`boot-descriptor-02`）：probe 加载、异步 start 返回 0，进程最终断言退出 1（非 timeout）。
- 真实 app 启动（`apk-recovery-02` / `manualtap-01`，pid 27088 / 29429）：见上文“尚未证明”，阻塞为 `main` init array 到索引 160 时的 guest SIGSEGV（`sdk+0x4db690` strcmp），不再是旧的未实现 `set` cmd5。

## 此检查点的限制

仅确认源码已完整救回、可严格构建、可被加载、线程栈与 applet focus/per-object 策略已修正、pctl factory/lifecycle 已建模、HIPC 描述符计数与 raw/domain 边界校验、set 现代 cmd5（语言表）已实现，并自带回归测试；头文件已重建并局部 ABI 验证，运行验证尚未完成。
游戏仍不可运行：`/sdcard/D3/RomFS` 缺失；boot 走到 `main` init array 索引 160 时 guest SIGSEGV 退出（见上文“尚未证明”）。
不要将历史文档中的“4/5 问题解决”或“编译成功”理解为游戏可运行；也不要把“旧 set cmd5 unsupported / 最新 set list 成功”理解为 set 0..6 全完成（旧 cmd1 `OutPointer` 仍 unsupported）。

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
