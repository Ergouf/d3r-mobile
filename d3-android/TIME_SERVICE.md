# D3HOST time:u 服务阶段（time service）范围与证据

日期：2026-10-16。本文只记录 `time:u` 服务阶段的范围、构建身份、真机结果、本轮新阻塞与回归真实原因；权威目标见 [GOAL.md](GOAL.md)，最新总体状态见 [RECOVERY.md](RECOVERY.md)，信号链阶段见 [SIGNAL_CHAIN.md](SIGNAL_CHAIN.md)。本文不修改 GOAL/RECOVERY/README，也不代表游戏可运行。

## 本阶段范围（做了什么）

实现 `time:u` 服务的根接口与 `GetTimeZoneService`，越过此前"iface 0 无效服务对象 / cmd3 被拒"的阻塞：

- 命名枚举 append：`D3_IF_TIME = 22`、`D3_IF_TIME_ZONE = 23`；端口枚举 append `PORT_TIME` / `PORT_TIME_ZONE`（`d3_service_names.h`）。
- `port_iface()`/`port_kind()`：`"time:u"` → `D3_IF_TIME`/`PORT_TIME`。
- `domain_command()`：`D3_IF_TIME` → `time_service_command()`；`D3_IF_TIME_ZONE` 仍走 unsupported（子对象命令暂未实现）。
- 根 cmd 3（domain）：`domain_add(session, D3_IF_TIME_ZONE)` 后 `reply_domain_object()`（恰好 1 个输出 domain 对象）；domain 表满时 `reply_domain()` 返回非 0、不输出对象。
- 根 cmd 3（非 domain）：在 HIPC handle slot 返回一个 move session handle，无额外 payload 字。
- `reply_prepare()` 的 domain 输出对象数默认 0，只有 `reply_domain_object()` 置 1（frame word = CMIF `DomainOutHeader.num_out_objects`）。
- `d3_handle_close(session)` 释放该 session 的全部 domain 对象；裸 HIPC close 也 close handle。

范围外（本阶段**未**实现）：`time:u` root cmd 20 `GetSharedMemory`（时钟共享内存）、时间/时钟值、TZ rule 等。当前 host **尚未接 sync**，故本 APK 仅含 signal 链 + `time:u` root。

## 构建身份与命令（time01）

宿主（host-only，恢复包自身 data roots，无 `--build-tests`）：

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/time-activity-01 \
  --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime \
  --private-root /data/user/0/com.d3mobile.host.recovery
```

- `libd3host.so` sha256 `c055a7ebe83ee4216907bf93e0d0400b7d290456c91b79d1c0729453e0b0a4f7`，394736 字节（严格构建 `-Werror`）。日志：`build/time-activity-01.build.log`。

打包/签名（复用既有 key 与 guest，离线，不安装）：

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py \
  --host d3-android/build/time-activity-01/libd3host.so \
  --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so \
  --keystore d3-android/build/apk-recovery-set02/local-debug.keystore \
  --output-dir D:/workspace/Diablo/d3-android/build/apk-recovery-time01
```

- APK sha256 `f13d4332e2e833a74f4aa97b6974bbc3e2fb1b6ef2a04a9d74456cbc67497592`，33661476 字节，v3 签名（v3 `true`；cert `CN=D3HOST Recovery Debug`，SHA-256 `10ef8aa7…dfee34f`，与 signal01 同一 key）。身份文件：`build/apk-recovery-time01/d3host-recovery-debug.json`。
- 包名固定 `com.d3mobile.host.recovery`；guest `libd3guest.so` sha256 `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`（33227200 字节）。keystore 未新建、mtime 未变（18:54:32）。

## 真实 Activity 结果（time-activity-01）

由 `tools/verify_activity.py` 驱动真实 Activity（非 native/命令行 probe），命令行见 `analysis/time-activity-01/runner_command.txt`（`--expected-apk-sha256 f13d…7592 --tap-start --duration-seconds 15 --stop-after`）。

- 设备 `R52T90127WT`；Activity `pid 12088` / guest 线程 `tid 12169`。
- `21:37:17.180` 进入 `nnMain`。
- **cmd3 成功**（`steps/041_logcat_slice.out` 行 897–899）：`svc domain time:u object 13 iface 22 cmd 3` → `ITimeService::GetTimeZoneService -> object 14`。即根对象 13 的 iface 为 **22（`D3_IF_TIME`，不再是 iface 0）**，cmd3 返回**一个** `ITimeZoneService` 对象 14。此前 `has no object 13 (iface 0)` 阻塞已越过。
- 原包未动：`original_unchanged=true`，`com.d3mobile.host` sha256 仍为 `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`；`markers_present=[]`。
- 恢复包身份匹配：`matches_expected=true`（安装 base.apk sha256 == `f13d…7592`）。
- 运行**未存活**（`app_alive=false`，`pid_last_seen=null`）：进程在 `nnMain` 后很快退出（下节）。

### 本轮新阻塞：root cmd 20 `GetSharedMemory` 未实现

- 紧接 cmd3 之后（`041_logcat_slice.out` 行 900、910–911），根对象 13 收到 **cmd 20（`0x14 GetSharedMemory`）**：`svc domain time:u object 13 iface 22 cmd 20` → `svc unimplemented ITimeService cmd=0x14 (?)`。该命令尚**未实现**，返回 unsupported。
- **ABI 注意**：日志中 `args=0xe` 是上一次 cmd3 回复遗留的 out-object（object 14 的字面量 0xe 是残留），**不是**本次请求的输入参数。该请求 CMIF 域 `data_size=0x10`，只有 CMIF 头、无实际输入参数（`041_logcat_slice.out` 行 901–902：SFCI + version 1 + cmd 0x14，其后全 0）。**不得据 `0xe` 反推 ABI**。

### 本轮新 crash 路径（正常暴露的新 guest 断言）

- `041_logcat_slice.out` 行 916–926：`appletOE` object 3 iface 4 cmd 22，报告错误 `0x278`（`svc domain appletOE object 3 iface 4 cmd 22 args=0x278`）。
- 行 927–954：guest `#0x26` → `Break(0)`（`assertion reason=0 ... lr=sdk+0x193ad8`），随后 `E D3Host : guest assertion Break(0)`。
- 行 955–956：`--------- beginning of crash` / `Fatal signal 6 (SIGABRT) ... in tid 12169 (d3-guest), pid 12088`。
- 行 957–984：正常 tombstone（`DEBUG`，`arm64`，`pid 12088, tid 12169, name: d3-guest`，`uid 10272`），backtrace 4 帧：`libc.so abort+160` → `libd3host.so fail+124` → `libd3host.so d3_hle_dispatch+4324` → guest 匿名段。即经 host `fail()` 上报的 guest 断言路径，属正常 ABRT。
- post crash dump（`post_evidence/files_d3-crash.txt`，sha256 `b16f8330c7209ec0ecf06e387a2bfa4ac89a629309b554aa057106ab8e97e173`）：`tag=d3crash`，`signal=6`，`tid = guest_tid = 0x2f89`，`last_kind=1`，`last_extra=0x26`，`lr=host+0x3b21ae5d8`，`x23=sdk+0x193ad8`。
- **定性**：这是 `nnMain` 之后一条**新的 guest 断言**在**正常**信号路径（guest 线程自身 SIGABRT）上的暴露；**不是**旧"非 guest 线程 JIT fault"的复发（该 fault 的 pc 落在 JIT-cache RX 段、tid ≠ guest_tid；本次 tid == guest_tid，走 libc abort）。renderer **尚未开始**（tombstone 无渲染栈），故不涉及图形呈现。

## 回归测试

### 当前有效结论：7 PASS（time-native-02）

最终轮 `time-native-02`：strict 构建 **exit 0**；沙箱先建 `data/logs`、`private/files`、`private/cache` 后，真机 `timeout 30s` 运行全部 **7** 个 Android 本机 suite，**全部 exit 0 / PASS**：

- `test_stack_memory`、`test_applet_focus`、`test_hipc_message`、`test_set_service`、`test_boot_sequence`、`test_signal_chain`、**`test_time_service`（本阶段新增，覆盖 root iface≠NONE、cmd3 恰好 1 个 child、两会话隔离/foreign id/close 失效、domain 表满非 0 无伪造 id、未知 root/child 命令被拒、非 domain cmd3 move session handle、whole-session close 释放 slot、裸 HIPC close）**。
- 日志：`build/time-native-02-results/*.out`。
- 旧测试 helper 已修复：`reply_parse` 改为**严格 `expected_objects` 参数化**（factory 输出 domain object 期望 1，标量/错误/句柄回复期望 0），**所有原有业务断言保留**（修正 frame word = CMIF `DomainOutHeader.num_out_objects` 的语义，不是服务端伪造对象）。

> 状态：**当前有效结论为 7 PASS。** 下列 time-native-01 的 5 PASS / 2 FAIL 为**历史记录**，其成因均已定性并修正。

### 历史：第一轮 time-native-01（5 PASS / 2 FAIL，已定性）

真机第一轮 `build/time-native-01-device.log`：**5 PASS / 2 FAIL**。

- PASS：`test_stack_memory`、`test_hipc_message`、`test_set_service`、`test_boot_sequence`、`test_time_service`。
- **FAIL `test_applet_focus` 行 85 `w[frame] == 1u`**：**测试 helper 的 bug，不是服务需伪造对象**。据 libnx，frame word 是 CMIF `DomainOutHeader.num_out_objects`——标量/错误/句柄回复应为 0，只有 factory 输出 domain object 才为 1。旧测试 helper（`reply_parse`）无条件要求 `==1`，与当前正确实现冲突。**已在 time-native-02 前的 helper `expected_objects` 参数化中修正。**
- **FAIL `test_signal_chain` 行 336（dump 检查）**：**环境失败，非代码回归**。沙箱 `private/files` dump 目录不存在（脚本未创建 `private/`），补建后该 suite PASS 并写出 `d3-crash.txt`。该失败记录如实保留在 `build/time-native-01-device.log`、`build/time-native-01.build.log`。

### 其他（由另一代理接线中，尚无 final 结果）

- `sync` 与 native 14-case（`test_sync`）单测已真机 PASS；但 **final 8-suite 全量与 SVC ABI** 仍由另一代理接线中，**本文暂不写其结果**，待其给出。

## 尚未证明 / 未消除

- `time:u` root **cmd 20 `GetSharedMemory`（时钟共享内存）未实现**，是本轮 `nnMain` 后的下一处明确阻塞；时钟值、TZ rule、sync 语义均未实现。
- `nnMain` 之后仍有新的 **guest 断言（Break(0)→SIGABRT）**，根因未定；**不等于** gameplay，游戏仍不可运行。
- APK 目前仅 signal 链 + `time:u` root；host 尚未接 sync。

## 不入 Git

APK、`libd3guest.so`、游戏二进制、签名私钥/keystore 均**不进入 Git**；本地 Git 不等于异地备份。构建产物在 `d3-android/build/`（已 ignored），证据在 `recovery/d3host-20261016-huRwPN/analysis/time-activity-01/`（ignored）。

## 附：本阶段相关文件

- `d3-android/host/d3_service.c`：`time_service_command`、`domain_command`（`D3_IF_TIME`/`D3_IF_TIME_ZONE`）、`d3_handle_close`/`domain_close_session`、`reply_domain_object`（主会话负责）。
- `d3-android/host/d3_service_names.h`：`D3_IF_TIME`/`D3_IF_TIME_ZONE` 与命令名表。
- `d3-android/tests/test_time_service.c`：本阶段新增 native 回归。
- `d3-android/tools/build_host.py`：`--build-tests` 注册 `test_time_service`。
