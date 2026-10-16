# D3HOST 同步原语阶段（sync）范围与证据

日期：2026-10-16。本文只记录 sync 阶段的范围、构建身份、真机结果与回归；权威目标见 [GOAL.md](GOAL.md)，最新总体状态见 [RECOVERY.md](RECOVERY.md)，前序阶段见 [SIGNAL_CHAIN.md](SIGNAL_CHAIN.md) 与 [TIME_SERVICE.md](TIME_SERVICE.md)。本文不代表游戏可运行。

## 本阶段范围（做了什么）

把 `SVC 0x1A..0x1D`（ArbitrateLock / ArbitrateUnlock / WaitProcessWideKeyAtomic / SignalProcessWideKey）从"空成功 stub（`set_saved(saved,0,0)` + 批量日志）"替换为真实的 host 侧同步实现：

- 新增独立模块 `host/d3_sync.c` + `host/d3_sync.h`，只依赖 pthread，自带 FIFO 等待队列（`SyncWaiter`）、`pthread_mutex`/`pthread_cond` 内部原语，以及经 `/proc/self/maps` 的地址校验。
- 语义：`d3_sync_lock`（owner/tag 校验）、`d3_sync_unlock`、`d3_sync_wait`（写入 key hint、释放 mutex、带超时等待；`timeout == 0` 直接返回 `0xea01` 且**不**重新获取，与 libnx/Atmosphere 一致）、`d3_sync_signal`。
- `host/d3_host.c` 的 `svc_call()` 接线：`0x1A → d3_sync_lock`、`0x1B → d3_sync_unlock`、`0x1C → d3_sync_wait`、`0x1D → d3_sync_signal`。
- `tools/build_host.py`：`HOST_SRC` 增加 `host/d3_sync.c`；`test_stack_memory`/`test_boot_sequence`/`test_signal_chain` 各增链入 `d3_sync.c`（它们 `#include` host.c）；新增第 8 个 suite `test_sync`。

**范围外（本阶段未解决 / 未实现）**：

- `0x1B` 传入的当前 tag 仍是 `D3_THREAD_ID`（=1，现有单 guest 上下文常量）。**`CreateThread`/`Start` 仍是 stub**，故这不构成"多 guest 线程调度"。
- 同步实现是启动子集：**FIFO，非优先级继承**；线程终止 / 取消 / `WaitSynchronization` 事件语义未做。
- root cmd20 `GetSharedMemory` 未实现（见下）。

## 构建身份与命令（sync01）

宿主（host-only，signal + time + sync 三模块，恢复包自身 data roots）：

```bash
bash d3-android/build.sh --output-dir D:/workspace/Diablo/d3-android/build/sync-activity-01 \
  --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime \
  --private-root /data/user/0/com.d3mobile.host.recovery
```

- `libd3host.so` sha256 `2b5173cdbaa6bafca90647fe4e567acf20f7deba58d5bc07252d0ab74b536464`，**416232 字节**（严格构建 `-Werror`；较 time01 的 394736 字节增加，即 sync 模块链接入）。日志：`build/sync-activity-01/build.log`。

打包/签名（复用既有 key 与 guest，离线）：

```bash
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/build_apk.py \
  --host d3-android/build/sync-activity-01/libd3host.so \
  --guest recovery/d3host-20261016-huRwPN/extracted/lib/arm64-v8a/libd3guest.so \
  --keystore d3-android/build/apk-recovery-set02/local-debug.keystore \
  --output-dir D:/workspace/Diablo/d3-android/build/apk-recovery-sync01
```

- APK sha256 `ec09528d3f4ecb9731447173314d8854dffbb18561085d315e0e08fcc67bd121`，**33677860 字节**，v3 签名（1 signer，cert `CN=D3HOST Recovery Debug`，SHA-256 `10ef8aa7…dfee34f`，与 signal01/time01 同一 key；keystore mtime 未变）。身份文件：`build/apk-recovery-sync01/d3host-recovery-debug.json`。
- 包名 `com.d3mobile.host.recovery`；guest `libd3guest.so` sha256 `dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`（33227200 字节，与 time01 同一 guest）。

安装与身份核对（安装后设备 base.apk 哈希与构建产物一致）：

```
/data/app/~~pWbEnfjslpOl2UIGI9hZbQ==/com.d3mobile.host.recovery-s0WX1x_3FAxIdGkFHnzBdA==/base.apk
ec09528d3f4ecb9731447173314d8854dffbb18561085d315e0e08fcc67bd121   ← 与构建产物相同
```

原包 `com.d3mobile.host` 未动：`original_unchanged=true`（sha256 仍 `1659b83628edaf0e3da72d8a54b4e7cf88dac80cd7c5ea240f8af5dcc95007e7`）。

## 真机结果（sync-activity-01）

由 `tools/verify_activity.py` 驱动真实 Activity（`runner_command.txt`：`--expected-apk-sha256 ec09…d121 --tap-start --duration-seconds 20 --stop-after`）。

- 设备 `R52T90127WT`；Activity `pid 14260` / guest 线程 `tid 14365`（`0x381d`）。`matches_expected=true`，`markers_present=[]`，`refused=false`。
- tap 真实命中启用按钮 "启动兼容层" center `[1280,235]`，`tap_rc=0`（`tap_start.json`）。
- 运行**未存活**（`app_alive=false`，`pid_last_seen=null`）：guest 在 `nnMain` 后很快以自身断言退出（下节）。

### 走到哪里：cmd3 成功，停在 root cmd 20

`post_logs_extract/d3-service.log` 与 logcat：

```
control time:u ConvertCurrentObjectToDomain -> object 13 (22)
domain time:u object 13 iface 22 cmd 3  args=0 0 0 0
ITimeService::GetTimeZoneService -> object 14        ← cmd3 成功（iface 22，不再是 iface 0）
svc cmif port=time:u cmd=20 …  0x14 0 0xe …
svc domain time:u object 13 iface 22 cmd 20 args=0xe 0 0 0
svc unimplemented ITimeService cmd=0x14 (?)          ← root cmd20 GetSharedMemory 未实现
svc cmif port=appletOE cmd=22 … 0x278 …
svc domain appletOE object 3 iface 4 cmd 22 args=0x278
Break assertion reason=0 arg=0x6d7ffff440 size=4 lr=…(sdk+0x193ad8)
E D3Host : guest assertion Break(0) lr=…(sdk+0x193ad8)
F libc   : Fatal signal 6 (SIGABRT), code -1 (SI_QUEUE) in tid 14365 (d3-guest), pid 14260
```

- **这是 guest 自身的断言**，不是 host bug：guest `#0x26`(Break) → `Break(0)`，host 随后走 guest 崩溃路径。tombstone：`libc.so abort+160` → `libd3host.so fail+124` → `libd3host.so d3_hle_dispatch+4556` → guest 匿名段。renderer 未开始。
- post dump（`post_evidence/files_d3-crash.txt`，sha256 `8306e17e92ea4880abbf00679fca68c56f280ebd20a247a2924a0f52d2506eb9`）：`signal=6`、`tid=guest_tid=0x381d`(=14365)、`last_kind=1`、`last_extra=0x26`。dump 在本轮确被重写（pre `9cf0f354…` → post `8306e17e…`；pre 为先前遗留 dump）。
- 与 `time-activity-01` 相比**同一签名、同一阻塞点**（time 轮：`signal=6`、`tid=guest_tid=0x2f89`、`last_kind=1`、`last_extra=0x26`）。即本阶段**未引入新的崩溃路径**，而是停在既有 cmd20 阻塞。

### SVC 序列是有界的（无 0x1c 忙循环）

同一 APK 的独立冷启动复测（清 logcat 后点击、8 秒窗口，`pid 15193` / `tid 16122`），复现完全一致的序列：

```
0x29=6  0x21=6  0x1d=6  0x6=5  0x16=5  0x2c=4  0xf=2  0x25=2  0xd/0xc/0x9/0x8=1
D3Host svc 行合计 49；SVC 计数器 svcs=0xbf (191)
```

- 该窗口内 guest 只发出 **`0x1d`(SignalProcessWideKey)**，**未发出 `0x1a`/`0x1b`/`0x1c`**——因为在需要真正等待之前就停在 cmd20 断言。
- 对比 `signal-activity-03`（time 修复之前）的 dump：`svcs=0x4779565`（约 7500 万）且 `svc #0x1c`（旧 stub 的批量日志格式 `svc #28 x0=… x1=… x2=1 x3=-1`）在采样中重复出现——即当时的 `0x1c` 忙循环。该忙循环在 **time 阶段（cmd3 生效）后消失**，不是本 sync 阶段引入的改动；本阶段的可证事实是：**含 sync 的当前 APK 其 SVC 序列有界（191），无 0x1c 忙循环**。

### 结论措辞（务必遵守）

- 只能写"**本 APK 的 SVC 序列有界（191 次）且未见 0x1c 忙循环；guest 在 cmd3 成功后停于未实现的 root cmd20，并以其自身断言（SIGABRT）退出**"，**不得**写成"同步已修好""线程同步已验证"。
- 同步模块本阶段**未被 guest 实际行使到**（未发出 0x1a/0x1b/0x1c），其正确性只由 native suite `test_sync`（15 例，含 SVC ABI）证明，**不等于**在真实 SDK 启动路径中被验证。
- `0x1B` 的 `D3_THREAD_ID=1` 是单 guest 上下文，**不**构成多线程调度证据。

## 回归测试

### 当前有效结论：android 本机 8 个 suite 全 PASS（sync-native-01）

严格构建 `--build-probe --build-tests` **exit 0**（`-Wall -Wextra -Werror`，8 个 suite 编译干净）；沙箱 `/data/local/tmp/d3host-recovery-huRwPN/sync-native-01` 先建 `data/logs`、`private/files`、`private/cache` 后，真机 `timeout 30s` 逐 suite 运行，**8/8 exit 0**：

- 既有 7 个（`test_stack_memory`、`test_applet_focus`、`test_hipc_message`、`test_set_service`、`test_boot_sequence`、`test_signal_chain`、`test_time_service`）
- **新增 `test_sync`（15 例）**：有界等待、`timeout=0` → `0xea01` 且不重获、超时语义、signal 竞态、交接、地址校验，外加 **SVC ABI 用例**（直接驱动真实 `d3_hle_dispatch`：`0x1A` tag 不匹配 → `x0=0` 且不写 word；`0x1B` owner 1 释放；`0x1C` `timeout=0` → `x0=0xea01` 且 mutex 释放、key hint 留 1；`0x1D` void、key 清零；保留 x1/x2 保存断言）。

- 日志：`build/sync-native-01/`（ignored）。
- Python（无设备）：`test_extract_apk.py` 9/9、`test_verify_activity.py` 11/11，各 exit 0；日志 `build/sync-unit-01/python-*.log`。
- **首轮曾 7/8**：`test_signal_chain` 在 dump 检查处失败（`FAIL line 336`）。成因为**测试夹具**——`dump_file()`（`host/d3_host.c:355`）不建目录，写 `private/files/d3-crash.txt`（回退 `private/cache`、`data/logs`）；夹具误把 `files`/`cache`/`logs` 建在顶层。改为正确层级后 **8/8**。**与模块/host 实现无关**。

## 尚未证明 / 未消除

- guest 线程在 ART 管理信号下仍有 **pre-handler 风险**（[SIGNAL_CHAIN.md](SIGNAL_CHAIN.md)），未消除。
- root cmd20 `GetSharedMemory` 未实现 → guest 断言退出；这是**下一步的启动阻塞**。
- `CreateThread`/`Start` 仍 stub；`WaitSynchronization` 事件语义缺；同步为 FIFO 非优先级继承。
- guest 源码重建工具 `build_guest_elf.py` 缺失，只能依赖保存的 `libd3guest.so`。
- RomFS / graphics / audio / input 均未实现；**游戏仍不可运行**。

## 复现

```
/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe -I d3-android/tools/verify_activity.py \
  --adb D:/workspace/Gdict/android_sdk/platform-tools/adb.exe \
  --output-dir <brand-new dir> \
  --expected-apk-sha256 ec09528d3f4ecb9731447173314d8854dffbb18561085d315e0e08fcc67bd121 \
  --tap-start --duration-seconds 20 --stop-after
```

- 该 CLI **没有 `--install`**；构建/打包/安装分别由 `build.sh` / `build_apk.py` / `adb install -r` 完成。
- 证据目录：`recovery/d3host-20261016-huRwPN/analysis/sync-activity-01/`（`summary.json`、`tap_start.json`、`steps/`、`pre_evidence/`、`post_evidence/`；`post_logs_extract/` 为本文解出的 `logs.tar` 副本）。

## 不入 Git

APK、`libd3guest.so`、游戏二进制、签名私钥/keystore 均**不进入 Git**；本地 Git 不等于异地备份。构建产物在 `d3-android/build/`（ignored）。

## 附：本阶段相关文件

- `d3-android/host/d3_sync.c`、`d3-android/host/d3_sync.h`：同步原语实现（新增）。
- `d3-android/host/d3_host.c`：`svc_call()` 的 `0x1A..0x1D` 接线。
- `d3-android/tests/test_sync.c`：本阶段新增 native 回归（15 例，含 SVC ABI）。
- `d3-android/tools/build_host.py`：`HOST_SRC` 与 `--build-tests` 注册。
