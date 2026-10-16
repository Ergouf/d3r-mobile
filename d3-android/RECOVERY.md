# D3HOST 源码恢复检查点

日期：2026-10-16
分支：`recovery/d3host-sources`　代码阶段 `4b8f419`（"preserve Android signal chain for non-guest threads"，signal 检查点）。此前阶段 `4eb34b9`（单次初始化修复）、`3595280`（独立测试 APK）、`ab074d3`（set 服务）；更早检查点打标签 `recovered-original-sources-20261016` = `3e1c61c`，无远程仓库。

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

## 当前状态（代码阶段 4b8f419，2026-10-16）

- signal 检查点 `4b8f419`（"preserve Android signal chain for non-guest threads"）：host 不再截获 ART 管理的信号，保留 Android 默认信号链。真机两次 Activity 按钮启动（`signal-activity-01` pid 7201/7304、`signal-activity-03` pid 10072/10167）均进入 `nnMain`，`markers[]`、原包 sha256 `1659b8…95007e7` 不变、无新 crash，ART `sig11`、7 个 user 线程与 kernel 线程不再混淆；两次都以 20 次采样（约 40s）观测。**注意：guest 线程自身的 ART pre-handler 风险仍 open**，故这只是 bounded 修复，不宣称所有 guest 信号已安全。
- `time` 根接口 / cmd3 已实现：root iface 22 → TZ iface 23 child，domain 数据与错误 `num_out_objects` 0、factory 1，含会话与 child-close 生命周期。`time-native02` 全部 7 个 suite 真机 PASS（applet 旧 helper 已改为精确 0/1，无断言跳过）。
- `time-activity-01` 真机（真实 APK `f13d4332…97592`、host `c055a7eb…b0a4f7`，pid 12088 / guest 12169）于 21:37:17 越过 cmd3 object 14。下一处是 root cmd20 `GetSharedMemory` unsupported → `error 0x278` → `Break0` → 正常 SIGABRT + debuggerd（post crash `b16f8330…e173`）。这是**新的 guest 断言**，不是旧的非 guest JIT fault 复发，**不是 app 运行成功**。
- `d3_sync`（lock/unlock/wait/signal）14 类 case standalone 真机 PASS。**范围**：这是启动子集的 lock/unlock/process-wide-key 实现，不是完整 Horizon 内核；模块为 FIFO 而非优先级继承，`SVC 0x1B` 仍按现存单 guest 上下文 tag1；线程终止 / 取消 / `WaitSynchronization` 事件语义未完，最终 tests 只钉已实现的子集。`0x1a..0x1d` 空成功 stub 已替换，最终 8-suite / SVC ABI 与最新 APK 结果尚待，**先如实标 pending**；真实 `Create/Start` 线程仍 stub。
- 以下为 `4eb34b9` 阶段（仍有效，保留，勿当最新）：单次初始化修复（`4eb34b9`，根因已定位并提交）：SDK 与 `main` 的 `DT_INIT` 本身已各自遍历完整 init 数组（`[0xc4bc88,0xc4bfe0)` = 107 项、`[0x215bed0,0x215ca10)` = 360 项），但 host 原先又用 `call_array` 跑了一遍；现删掉 `call_array`，仅保留两个 `DT_INIT`。`6df9de6` 上这次重复遍历把 `ItemLock` 对象的链表链接二次清零，即旧 `main[160]` 的 `sdk+0x4db690` SIGSEGV；真机 `config-01` 内存证明链头已指向 `ItemLock` 对象，**不是缺数据或 guest 空 map**。
- 严格 NDK 构建 7 个产物全部通过：`libd3host.so`、`d3_probe` 与 5 个 native test。
- 5 个 Android 本机 suite 真机全部 PASS（`config-02`）：`test_stack_memory`、`test_applet_focus`、`test_hipc_message`、`test_set_service`、`test_boot_sequence`（新增，synthetic guest 107/360 构造计数）。从 `6df9de6` snapshot 编译同一测试则红灯（exit 1 at `sdk_ctor_calls` 断言），可钉住该修复。test helper 亦已修复：`CHECK` 结果传播至 `main`，frame 显式 16B 对齐。
- 9 个 Python 提取测试 PASS。
- 对 `4eb34b9` 做干净 `git archive`，7 个 native 产物严格构建、9 项 Python 测试通过，并用外部 guest 与既有 debug key 打包签名（`apksigner verify` PASS）。**仅证明已跟踪源码/打包输入完整**；未在设备执行此归档产物，`libd3guest.so` 与 key 本就不入 Git。

## 尚未证明（勿读作“可运行”）

- 游戏不可运行，仍无 game loop；signal/time 的进展都不等于可玩。
- 旧 `main[160]` `ItemLock` SIGSEGV 已由单次初始化修复解决，**应视作历史**；首次进入 `nnMain` 见 `config-02`。
- **已被最新状态替代（历史，保留证据）**：旧 `time:u` cmd3 被拒（`has no object 13`、iface 0）与 SVC `0x1c` 空转 stub 属于 `config-02` 阶段；现 `time` 根接口 / cmd3 已实现（见“当前状态”）。真实 `Create/Start` 线程调度与 `WaitSynchronization`/events 仍在推进中，`0x1c` stub 的替换尚未终验。
- **已被最新状态替代（历史，保留证据）**：旧 `config-02` 的 `fault pc=0x4804f37c`、`tid32150 != guest32139`（非 guest 线程）及 `pid32404` no-handler 忙循环对照为当时现象。host 原始 raw signal handler 截获 ART 管理信号（旧“待证假设”）已由 `4b8f419` 处理，真机两次 Activity 启动无新 crash。但这是 bounded 修复：**guest 线程自身的 ART pre-handler 风险仍 open**，不宣称所有 guest 信号已安全、不宣称应用不再闪退。
- 当前下一处阻塞：`time-activity-01` 越过 cmd3 object 14 后，root cmd20 `GetSharedMemory` unsupported → `error 0x278` → `Break0` → 正常 SIGABRT + debuggerd（**新的 guest 断言**，非旧非 guest JIT fault 复发，非 app 运行成功）。
- 真正 guest 线程调度仍未完成（Create/Start 仍只分配 handle / 返回成功 stub）。
- `/sdcard/D3/RomFS` 缺失；graphics/audio/input 与可玩版本的 APK 部署未完成。
- 严格构建与 native 测试都不等于 gameplay，不能让游戏跑起来。
- 证据（ignored）：新增 `analysis/signal-activity-01/`、`signal-activity-03/`、`time-activity-01/`（最新，含 `steps/`、`summary.json`、`*_evidence/`）；历史 `analysis/apk-config02-logcat.txt`（`nnMain` 833..838，time:u/cmd3/SVC 0x1c 855..913）、`apk-config02-crash.txt`、`apk-config02-default-handler.log` / `-pid32404-full.log` / `-default-handler.maps` / `-threads.log`。

## 历史检查点（各一行，勿当作“永远最新”）

- `4eb34b9`：单次初始化修复（删掉重复的 `call_array`，仅保留两个 `DT_INIT`）；7 个 native 产物严格构建、5 个 Android-native suite + 9 个 Python 测试通过。
- `ab074d3`：set 现代 cmd5（`GetAvailableLanguageCodes2`）经 bounded HIPC buffer 返回 18 语言码（`en-US` index 1），22-bit addr-high / 36-bit size，bounded `process_vm_writev` self-copy；旧 cmd1 `OutPointer` 仍 unsupported（**不能说 0..6 全完成**）。
- `3595280`：独立恢复 APK 诊断 shell。`325fcdd`：定位 CMIF frame 前统计 HIPC 描述符并校验 raw/domain 边界。`0f973c2`：解析无 CMIF payload 的 domain-close。
- `c95cac0` / `3d9dfe3`：不再 join 已 detach 的 guest 线程；pctl factory 0/1 与 child Initialize。`c25ab68` / `9fa57f9` / `3d5d416`：完整 1 GiB 栈区 GetInfo 14/15；`ISelfController` cmd16 per-object；domain 转换返回分配的 root。

## 恢复 APK 诊断 shell（包名 `com.d3mobile.host.recovery`）

- 固定包名，与原 `com.d3mobile.host` 分离，**不覆盖**原 APK（原 APK SHA-256 保持 `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`，本轮再次 verify 一致）；原包自身的 `g_table` 闪退仍是独立未决问题，**勿与新包混同**。
- 真机平板 `R52T90127WT` 已安装（UID 10272），由 Activity 启动；新宿主库 `System.loadLibrary` 成功加载，guest 33,227,200 bytes 来自原 APK。
- 内部 root `/data/user/0/com.d3mobile.host.recovery/files/runtime`；private root `/data/user/0/com.d3mobile.host.recovery`；`build_host.py` 已支持 `--data-root`/`--private-root`，与 `--sandbox-root` 互斥。
- 诊断 UI 已在 Android 16（target 36）修 NoActionBar + WindowInsets + dark status icons；截图 `../recovery/d3host-20261016-huRwPN/analysis/apk-recovery-ui-03.png`。默认不 autostart，按钮一次；`Intent autostart=true` 可测试。
- 最新一轮真机为 `signal-activity-01` / `-03`（signal，`4b8f419`）与 `time-activity-01`（time，APK `f13d4332…97592`），均用 `verify_activity.py` 通过真实 Activity 启动按钮；更早 `config-02` 于 19:57:33 首次进入 `nnMain`（见“尚无证明”）。
- 有 UI 不代表游戏画面可用：启动 guest 后进程仍退出。证据（ignored）`analysis/signal-activity-01/`、`signal-activity-03/`、`time-activity-01/`、`apk-config02-logcat.txt`、`apk-config02-crash.txt`。

## 离线打包

- `tools/build_apk.py` 用新构建的 host 与保存的 guest 打包并签名 debug APK，`--host`/`--guest` 均为必需输入，不 glob “最新” `.so`；`--keystore` 复用既有本地调试 keystore（不入 Git），换输出目录也复用以避免 UPDATE_INCOMPATIBLE。
- 已验证流程（相对 repo 根，固定包名防覆盖；`config-02` / `apk-recovery-config02`）：

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/config-02 --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --build-probe --build-tests
```

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py --host d3-android/build/config-02/libd3host.so --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so --keystore d3-android/build/apk-recovery-set02/local-debug.keystore --output-dir d3-android/build/apk-recovery-config02
```

## 工具范围

`build.sh` / `tools/build_host.py` / `tools/build_apk.py` 只做编译、设备端 native probe/test 构建与离线打包；不安装、也不替换设备上已安装的 APK（实际 `adb install -r` 在用户授权的真机验证中单独执行），不选择存根源码，不拷贝旧头文件。

## 设备加载与启动测试

隔离测试目录：`/data/local/tmp/d3host-recovery-huRwPN`。

- 加载旧 APK 宿主：退出码 3，缺少 `g_table`。
- 加载恢复宿主：`RTLD_NOW` + `d3_host_start` 退出码 0。
- 线程栈根因已修正，Android 本机 `test_stack_memory` PASS（含 32 次往返与边界拒绝）；`test_applet_focus` PASS；`test_hipc_message` PASS；`test_set_service` PASS；`test_boot_sequence` PASS。
- 最新隔离 boot（`boot-descriptor-02`）：probe 加载、异步 start 返回 0，进程最终断言退出 1（非 timeout）。
- 真实 app 启动（`apk-config02`，Activity `pid32104` / guest `pid32139`，历史）：见上文“尚未证明”，首次进入 `nnMain`。最新真实 Activity 启动为 `signal-activity-01` / `-03` 与 `time-activity-01`（`verify_activity.py`，真实按钮），当前阻塞是 root cmd20 `GetSharedMemory` unsupported（见“当前状态”与“此检查点的限制”）。

## 此检查点的限制

仅确认源码已完整救回、可严格构建、可被加载、线程栈与 applet focus/per-object 策略已修正、pctl factory/lifecycle 已建模、HIPC 描述符计数与 raw/domain 边界校验、set 现代 cmd5（语言表）、单次初始化修复已实现，并自带回归测试；头文件已重建并局部 ABI 验证。signal 检查点 `4b8f419` 与 `time` 根接口 / cmd3 已在真机验证（见“当前状态”）。
游戏仍不可运行：`/sdcard/D3/RomFS` 缺失；`time-activity-01` 越过 cmd3 object 14 后停在 root cmd20 `GetSharedMemory` unsupported（`error 0x278` → `Break0` → 正常 SIGABRT + debuggerd）；真实 guest 线程调度、`WaitSynchronization`/events 未完。
不要将历史文档中的“4/5 问题解决”或“编译成功”理解为游戏可运行；也不要把“旧 set cmd5 unsupported / 最新 set list 成功”理解为 set 0..6 全完成（旧 cmd1 `OutPointer` 仍 unsupported）；不要把 `d3_sync` 子集 PASS 理解为完整同步/真实线程已完成。

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
