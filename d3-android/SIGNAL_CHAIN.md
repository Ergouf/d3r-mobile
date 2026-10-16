# D3HOST 信号链阶段（signal chain）范围与证据

日期：2026-10-16。本文只记录 signal 阶段的范围、复现命令、构建身份与结果；权威目标见 [GOAL.md](GOAL.md)，最新总体状态见 [RECOVERY.md](RECOVERY.md)。本文不修改 GOAL/RECOVERY/README，也不代表游戏可运行。

## 本阶段范围（做了什么）

把 host 的崩溃信号安装从"raw `rt_sigaction` 直接替换内核 handler"改为经 libc `sigaction` 安装，使 ART 的 signal chain 保持在用户动作之前：

- `install_signal_actions()` 由 `pthread_once` 执行一次；`sigaction(sig,0,&g_previous_signals[sig])` 只保存一次此前用户动作，安装时保留 `sa_mask` 与 `SA_RESTART`/`SA_NODEFER`。
- `chain_signal()` 处理此前动作：普通 handler / `SA_SIGINFO` / `SA_RESETHAND` / `SIG_IGN`（同步故障被忽略则转默认）；真正致命时 `default_signal()` 用 raw syscall 重设 `SIG_DFL` + `tgkill` + `RT_SIGPROCMASK` 解除阻塞，**不再 `exit_group(1)`**。
- `crash_handler()`：非 guest 线程第一时间直接 `chain_signal`，不触碰 tp/x18、不写 dump；guest 线程才写 dump 并链式调用此前动作，返回前恢复进入 handler 时的 tp/x18。
- 删除旧的 `d3_sigreturn`/`D3_SA_*` 宏；日常安装经 libc，`raw_sigaction` 仅用于读取内核视图及最终默认致命动作的重发。新增日志字段 `user/ours/kernel/chained`。

范围外（本阶段**未**解决）：`time:u` cmd3 与 `SVC 0x1c` 仍未实现；真实 guest 线程在 ART pre-handler 阶段的 TLS 访问风险仍在（见"尚未证明"）。

## 构建身份与命令

宿主（既有命令，沙箱指向恢复包自身路径）：

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/signal-activity-01 \
  --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime \
  --private-root /data/user/0/com.d3mobile.host.recovery
```

- `libd3host.so` sha256 `14ceacbbbd1a401952622baae2cb0f1573db428163a190f0ccf8063b2a39b8e1`，385496 字节（严格构建，`-Werror`）。构建日志：`build/signal-activity-01.build.log`。

打包/签名（既有命令，离线，不安装）：

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py \
  --host d3-android/build/signal-activity-01/libd3host.so \
  --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so \
  --keystore d3-android/build/apk-recovery-set02/local-debug.keystore \
  --output-dir D:/workspace/Diablo/d3-android/build/apk-recovery-signal01
```

- APK sha256 `2673e2deebd33183a63fbee0559ec02980b67e31d7fb7366a0676f254af5112e`，33,645,092 字节，v3 签名。
- 身份文件：`build/apk-recovery-signal01/d3host-recovery-debug.json`。
- 包名固定 `com.d3mobile.host.recovery`；guest `libd3guest.so` sha256 `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`（33,227,200 字节）。

## 真实 Activity 结果（signal-activity-01）

由 `tools/verify_activity.py` 驱动真实 Activity（非 native/命令行 probe），命令行：

```
d3-android/tools/verify_activity.py --adb D:/workspace/Gdict/android_sdk/platform-tools/adb.exe \
  --output-dir D:/workspace/Diablo/recovery/d3host-20261016-huRwPN/analysis/signal-activity-01 \
  --expected-apk-sha256 2673e2deebd33183a63fbee0559ec02980b67e31d7fb7366a0676f254af5112e \
  --tap-start --duration-seconds 20
```

- 设备 `R52T90127WT`；Activity `pid 7201` / guest 线程 `tid 7304`；安装线程 `tid 7303`。
- `21:15:26.613` 日志 `call nnMain`（进入 `nnMain`）。
- `21:15:26.580` 在 Activity 进程 `pid 7201` / `tid 7303` 上的 `install_signal_actions` 记录（`steps/131_logcat_pid.out` 行 100–106）：`sig 11`(SEGV)/`sig 7`(BUS)/`sig 31`(SYS) 为 `chained=1`（`user=0x6e1774abe0`、`kernel=0x71ad472b18`，内核槽与用户动作不同 → ART 调度器仍在更前一层）；`sig 4`(ILL)/`sig 5`(TRAP)/`sig 6`(ABRT)/`sig 8`(FPE) 为 `chained=0`（`user=kernel=0x6e1774abe0` → ART 未 claim 这些信号，libc 自身处置与用户动作一致）。**同一 ART 进程内两类共存**：SIGSEGV/SIGBUS 仍走 ART 链，ART 未 claim 的信号走 libc 路径。结论一律以真实 pid+tid 为准，不据 handler 数值反推或猜测进程。
- 运行 20 次采样（`--duration-seconds 20` 是采样迭代数，含每轮取证开销，实测总时长约 40 秒）后 `app_alive=true`（`pid_last_seen=7201`），`any_required_failed=false`，`markers_present=[]`。
- crash 文件哈希未变：`files/d3-crash.txt` 与 `cache/d3-crash.txt` 运行前后均为 `9b7170adf1363bcc992c10d34b02d1407b7fd8da19fc526251fa5749d366556b`（该 dump 为**既有旧 dump**，本次运行未写新的 guest crash）。
- 原包未动：`original_unchanged=true`，`com.d3mobile.host` sha256 仍为 `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`。
- 证据：`recovery/d3host-20261016-huRwPN/analysis/signal-activity-01/`（`summary.json`、`steps.json`、`steps/`）。

### 结论措辞（务必遵守）

- 只能说"**在 20 次采样（配置 `--duration-seconds 20` + 取证开销，实测约 40 秒）窗口内未复现非 guest 崩溃**"，**不能**写成"非 guest 问题已完全解决"。仅以此采样窗口为准；其长度不是精确 20 秒。
- native 的 fake-TLS 用例**不等于** ART：它无法覆盖 ART pre-user pthread 阶段的 TLS 访问。

## 回归测试

- 6 个 Android 本机 suite 在真机 final 轮 `signal-native-04` **全部 PASS**（`test_stack_memory`、`test_applet_focus`、`test_hipc_message`、`test_set_service`、`test_boot_sequence`、`test_signal_chain`）；结果保存在 `build/signal-native-04-results/`。
- 9 项 Python 提取测试与 11 项取证脚本安全回归 PASS。
- 早期 native 轮 `signal-native-02`/`signal-native-03` 因**测试自身的错误**红过（02：case 6 断言方向写反；03：dump 读回匹配串写成非零填充十进制），已在 source 修正；两轮失败证据如实保留在 `build/signal-native-02-results/`、`build/signal-native-03-results/`，不作为通过结果。
- `test_signal_chain` 覆盖：普通/`SA_SIGINFO` 此前动作各链式一次且可返回、重复安装只链一次、非 guest 线程保留自身 tp/x18、guest 线程链在登记 host TLS 上执行并在返回前恢复中断的 fake guest tp/x18 且写出 `tag/signal/guest_tid` dump、`SIG_DFL` 以真实信号退出（`WTERMSIG`）。
- 未标记成功项：`no-handler`（bionic debuggerd）路径未在本测试中作为成功例，未纳入。

## 尚未证明 / 未消除

- `time:u` 仍返回 **iface 0 的无效服务对象**，request **cmd3 被拒**（`has no object 13 (iface 0)`），并出现 **`SVC 0x1c` 忙循环**（`svc #0x1c`）。示例：`time:u object 13 iface 0 cmd 3`、`time:u has no object 13 (iface 0)`、`ConvertCurrentObjectToDomain -> object 13`。本阶段未修。
- 真实 guest SIGSEGV 时仍存在 **guestTP 风险**：AOSP 证实 ART 在 pre-user pthread 阶段会访问 TLS，native 的 fake-TLS 用例覆盖不到该层；该风险**未消除**，仅在本 20 次采样窗口未复现。
- `verify_activity.py` 的 `ps` 采样：首轮 `CP` 字段在设备上不存在（导致 ps 打印帮助），记为该轮 **optional** 失败；已改为 `PID,TID,STAT,NAME,TIME,CPU`，并在 `signal-activity-03`（`steps/143_iter20_ps_T`、`145_iter20_task_stat`，rc0、stderr 为空）上真机确认命令可用。仅证明采样命令能跑通，**不**由此宣称 CPU 行为已有结论。
- 仅走完 `nnMain` 与 20 次采样存活，**不等于** gameplay；游戏仍不可运行。

## 复现（下一次重复运行）

- 隔离恢复包的重跑用**已构建 APK 的哈希**驱动（脚本从不安装，但会停止、启动恢复包并点击按钮）：

```
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/verify_activity.py --adb <abs adb> \
  --output-dir <brand-new dir> \
  --expected-apk-sha256 2673e2deebd33183a63fbee0559ec02980b67e31d7fb7366a0676f254af5112e \
  --tap-start --duration-seconds 20
```

- 该 CLI **没有 `--install`**；构建/打包/安装分别由既有命令完成（`build.sh` / `build_apk.py`，安装需另行授权）。
- 不要在真机上留下 `no-handler`/`pause`/`selftest-crash`/`trace` 等诊断标记；脚本会因标记存在而拒绝对该状态下做正常验收。
- 对应代码检查点的 Git 提交标题为 `fix: preserve Android signal chain for non-guest threads`。
- `signal-activity-02`（重复运行）**未构成正常启动证明**：`steps/019_uiautomator_read.out` 显示 UI 全部被 `com.android.systemui` 的 `notification_panel`/`legacy_window_root`（快捷设置面板）覆盖，界面内**无 recovery 启动按钮**，脚本据此**正确拒绝 tap 并 `exit 1`**。这是夹具环境（系统通知面板遮挡）导致的拒绝，**不是 guest crash、不是回归**，不计入结果。

### signal-activity-03（第二次独立冷启动，bounded 成功）

- 命令行（`runner_command.txt`）：`--expected-apk-sha256 2673e2de…112e --tap-start --duration-seconds 20 --stop-after`。
- `summary.json`：`refused=false`、`markers_present=[]`、`any_required_failed=false`、`app_alive=true`、`pid_last_seen=10072`、`matches_expected=true`、`original_unchanged=true`。
- tap 真实命中：`tap_start.json` 启用按钮 "启动兼容层" center `[1280,235]`，`tap_rc=0`（与 02 的面板遮挡拒绝相反）。
- 启动：installer `tid 10166` 于 `21:25:52.311` 记录 `sig 11`/`sig 7` `user=0x6e17c15be0 ours=1 kernel=0x71ad472b18 chained=1`；guest 线程 `tid 10167` 于 `21:25:52.347` `call nnMain 6e0f660480`。
- 20 次采样（配置 20 秒 + 取证开销，实测约 40 秒）内 `alive`；随后 `--stop-after`（step `153_stop_after`）主动 force-stop，避免继续空转烧 CPU。
- crash 哈希未变：`files/d3-crash.txt`、`cache/d3-crash.txt` 前后均 `9b7170adf1363bcc992c10d34b02d1407b7fd8da19fc526251fa5749d366556b`（旧 dump，本次未写新的 guest crash）。
- 线程采样：`steps/143_iter20_ps_T.out`（列 `PID TID STAT NAME TIME CPU`，stderr 为空，rc0）与 `steps/145_iter20_task_stat.out`；`verify_activity.py` 的 `CP` 修正在真机 `rc0` 生效。
- 与 `signal-activity-01`（pid 7201）不同 pid，属第二次独立冷启动的 bounded 证据。

其它 stage（`time:u`/cmd3/`SVC 0x1c`、guestTP ART 风险）**未解决、不因此改变**；20 次采样的 bounded 窗口仍不等于 gameplay。

## 不入 Git

APK、`libd3guest.so`、游戏二进制、签名私钥/keystore 均**不进入 Git**；本地 Git 不等于异地备份。构建产物在 `d3-android/build/`（`build/` 已 ignored）。

## 附：本阶段相关文件

- `d3-android/host/d3_host.c`：`install_signal_actions` / `chain_signal` / `default_signal` / `crash_handler`（主会话负责）。
- `d3-android/tests/test_signal_chain.c`：本阶段新增 native 回归。
- `d3-android/tools/build_host.py`：`--build-tests` 注册 `test_signal_chain`。
- `d3-android/tools/verify_activity.py`：真实 Activity 证据采集（可复用）。
