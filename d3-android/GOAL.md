# D3HOST 当前 Goal

设定日期：2026-10-16。最新验证状态见 [RECOVERY.md](RECOVERY.md)；本文件定义目标与验收条件，不代表这些功能已经完成。

## 总目标

使用原始 ARM64 guest 机器码，开发专用 Horizon/Switch 兼容层并封装为 Android APK，让 Diablo III 在真实 Android 平板上可玩。**不重写游戏自身的 C++，不转向仅能编译的演示存根。**

最终完成标准：真实 APK 能进入游戏，有实际游戏画面、基本音频和可用输入，能够操控角色移动并完成一次战斗；冷启动可复测，运行不依靠跳过断言、吞掉崩溃或伪造成功。

## 当前阶段目标

**越过 `nnMain` 后的 `time:u` 根接口 / domain / cmd3 这条启动阻塞（已完成），并推进到下一处可验证的游戏启动阶段。**

基线：检查点 `4b8f419`（signal）。真实 Activity 启动按钮两次进入 `nnMain`；`time:u` 根接口与 cmd3 已实现。游戏仍不可玩；进入主入口不算总目标完成。

- [x] 非 guest 线程退出问题：`4b8f419` 保留 Android 信号链（ART `sig11`、7 个 user 线程与 kernel 线程不再混淆），真机无新 crash。**guest 线程自身的 ART pre-handler 风险仍 open**，故信号修复是 bounded 的，不宣称所有 guest 信号已安全。
- [x] 按 guest 请求实现 `time:u` 根接口（root iface 22 → TZ iface 23 child）、domain 对象（`num_out_objects` 0、factory 1）与 cmd3，含会话与 child-close 生命周期。真机 `time-activity-01` 已越过 cmd3 object 14。
- [x] 替换 `SVC 0x1c` 的无条件成功存根，实现本启动路径需要的同步等待与唤醒（`d3_sync`：lock/unlock/process-wide-key；SVC `0x1A..0x1D` 已接线）。**范围说明**：这是启动子集，不是完整 Horizon 内核——模块 FIFO 而非优先级继承；`SVC 0x1B` 仍传现存单 guest 上下文 `D3_THREAD_ID=1`；线程终止 / 取消 / `WaitSynchronization` 事件语义未完，真实 `Create/Start` 线程仍 stub；**guest 启动路径尚未行使到 0x1a/0x1b/0x1c**（停在 cmd20 前），故同步只由 native `test_sync`（15 例含 SVC ABI）证明。回归：android 本机 8 suite 全 PASS（`sync-native-01`）、Python 9/9 + 11/11。证据与定性见 [SYNC.md](SYNC.md)。
- [x] 在独立恢复 APK 的真实 Activity 中复测，记录越过这些阻塞后的下一条明确启动证据：`time-activity-01`（APK `f13d4332…97592`、host `c055a7eb…b0a4f7`）于 21:37:17 越过 cmd3 object 14；下一处是 root cmd20 `GetSharedMemory` unsupported → `error 0x278` → `Break0` → 正常 SIGABRT + debuggerd。

### 当前阶段验收

1. 在平板 `R52T90127WT` 上，从真实 Activity 的启动按钮进入兼容层；不能仅用 native 测试或命令行 probe 代替。
2. `time:u` 回复符合请求协议与对象生命周期；同步调用具有正确的等待、唤醒及超时语义，不用伪造返回值掩盖缺失实现。
3. 正常诊断配置下启动继续推进；`no-handler`、暂停标记或跳过断言不能作为修复成功的条件。
4. 原有 native/Python 回归不退化，新增行为有针对性测试；保存构建身份、logcat、故障证据和对应 Git 检查点。
5. 若推进后遇到资源缺失或新的未实现接口，明确记录新的阻塞，不将其写成“游戏已运行”。

## 剩余工作大块（不编完成百分比 / 工期）

按依赖顺序列出尚待完成的大块。仅为范围，非估算；具体工期由主会话判断。

1. **guest 线程真实调度**：`Create/Start` 仍只分配句柄 / 返回成功 stub；`WaitSynchronization` 与 events 仍缺。需真实线程创建、等待队列与唤醒。
2. **SVC / 同步 ABI 收尾**：`d3_sync` 已接线并回归（8 suite PASS），但只是启动子集（lock/unlock/process-wide-key；FIFO，非优先级继承；`0x1B` 仍单 guest tag1），且 guest 启动路径尚未行使到 0x1a/0x1b/0x1c。线程终止 / 取消 / `WaitSynchronization` 事件语义仍属此块。
3. **下一处启动接口**：root cmd20 `GetSharedMemory` 目前 unsupported（`error 0x278` → `Break0` → SIGABRT）；需按协议实现并继续推进。
4. **guest 重建路径**：源码重写器 `build_guest_elf.py` 缺失，无法从 Git 重建 guest，只能依赖保存的 `libd3guest.so`。需恢复或重写该工具。
5. **ART pre-handler 信号风险**：guest 线程在 ART 管理信号下仍有 pre-handler 风险，属未决，需专门验证与修复。
6. **资源与呈现**：RomFS / 文件系统、graphics、audio、input 以及可部署的可玩构建均未实现。

## 后续阶段

- 接入合法已有的游戏资源与 RomFS；缺少数据时如实标记阻塞，不伪造内容。
- 完成实际 guest 多线程调度与内存、文件系统等必要运行时能力。
- 实现图形呈现、输入和音频，验证实际游戏交互。
- 达到总目标的冷启动、基本玩法与可重复运行标准。

## 执行边界

- 真机测试使用 `com.d3mobile.host.recovery`；未经另行明确授权，不覆盖原 `com.d3mobile.host`，不卸载原包或清除其数据。
- 使用恢复的正确 host 源码，不把 `*_minimal.c`、`*_new.*` 等历史存根当作正式实现。
- 有经过验证的阶段成果就提交 Git；不自动删除未跟踪的恢复源码。
- APK、guest/游戏二进制、密钥、签名私钥和内存转储不进入 Git；本地 Git 不等于异地备份。
- 常规、小范围任务优先交给 Sonnet 子代理；主会话负责根因判断、整合与最终真机验收。
- 日常可逆工作自主推进；覆盖原应用、删除数据或其他真正需要用户决定的操作必须另行确认。
