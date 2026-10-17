# D3 guest 符号表与 hook 表

## 1. 符号表怎么来的

guest (`libd3guest.so`) 是**合并并剥离**过的镜像：没有 `.symtab`，`.dynsym` 只有 2 条，
15,239 个 `_ZN2nn*` 只是散落字符串，没有任何指针/偏移表可反查。因此符号必须从**你自己拥有的游戏文件**里取：

1. `hactool -k prod.keys -t xci --securedir=ncas <xci>` 解出 NCA
2. `hactool -k prod.keys -t nca -i <nca>` 找到 **Program** 类型那个（Title ID `01001b300b9be000`）
   - 基础版：`244b84153edddf42407aa2a03572202a.nca`（14.27 GB）
   - **更新版：`ee56073dd35eb14eb7ea9ecd06c2e476.nca`（3.59 GB）← APK 里的 guest 来自这个**
3. `hactool -k prod.keys -t nca --exefsdir=exefs <nca>` → `main / sdk / rtld`(NSO0)
4. `hactool -t nso --uncompressed=sdk.nso0 exefs/sdk` 解压
5. 用 `reference/parsenso.py` / `reference/symmap.py` 解析 `.ro` 里的 MOD0 → DT_SYMTAB/DT_STRTAB
   → `sdk.symbols.json`（25,142 个符号，值是 sdk 模块内偏移）

## 2. 模块基址

合并镜像里 **sdk 模块位于 vaddr `0x10000`**。验证方法：取更新版 sdk 的 `.text` 随机 300 个
40 字节片段在 guest 里搜索，**300/300 命中且偏移恒为 0x3f00**（文件 0x100 → 客人 0x4000）。

所以：

```
guest_vaddr = 0x10000 + sdk_symbol_offset
```

逐字节校验过的例子：

| 符号 | sdk 内偏移 | guest vaddr |
|---|---|---|
| `_ZN2nn4time10InitializeEv` | 0x38e2d0 | 0x39e2d0 |
| `_ZN2nn2oe10InitializeEv` | 0x32b450 | 0x33b450 |
| `_ZN2nn2fs22QueryMountRomCacheSizeEPm` | 0x2175f0 | 0x2275f0 |

注意：**基础版 NCA 与 guest 不匹配**（38/300 命中且偏移不一致），必须用更新版。

## 3. hook 机制

在 `load_guest()` 里、重定位之后、`protect_guest_segment()` 之前，把目标函数入口改写成 16 字节跳板：

```
ldr x16, #8     0x58000050
br  x16         0xd61f0200
.quad host_fn
```

`x0..x7`（guest 参数）与 `x30`（返回地址）原样不动，宿主函数以 guest ABI 运行并直接返回给 guest 调用者。
实现见 `d3-android/host/d3_host.c` 的 `g_hooks[]` / `install_guest_hooks()`。

## 4. 当前 hook 表

| guest vaddr | 符号 | 行为 |
|---|---|---|
| 0x39e2d0 | `nn::time::Initialize` | 返回 0（不再连 time 服务，绕开 `GetSharedMemory`/0x2a2） |
| 0x39e5e0 | `nn::time::IsInitialized` | 返回 1 |
| 0x3a14a0 | `StandardUserSystemClock::GetCurrentTime` | 写 `time(NULL)`，返回 0 |
| 0x3a1520 | `StandardUserSystemClock::now` | 返回 `time(NULL)` |
| 0x3a1820 | `nn::time::ToCalendarTime` | `localtime_r` |
| 0x37b2e0 | `nn::socket::Initialize` | 返回 0 |
| 0x37b300 | `nn::socket::Finalize` | 返回 0 |
| 0x90650 | `nn::applet::SetCpuBoostMode` | 返回 0 |
| 0x2275f0 | `nn::fs::QueryMountRomCacheSize(Pm)` | 写 32 MiB |
| 0x227710 | `nn::fs::QueryMountRomCacheSize(Pm,AppId)` | 写 32 MiB |
| 0x227830 | `nn::fs::QueryMountRomCacheSize(Pm,i)` | 写 32 MiB |
| 0x227960 | `nn::fs::MountRom(Pc,void*,u64)` | 返回 0 |
| 0x227af0 | `nn::fs::MountRom(Pc,AppId,void*,u64)` | 返回 0 |
| 0x227c80 | `nn::fs::MountRom(Pc,i,void*,u64)` | 返回 0 |

## 5. romfs 结构（Program NCA 的 section 1）

```
0/                     ← 可执行体（main / main.npdm / rtld / sdk）
1/                     ← 游戏数据
  CPKs/Act1..Act5.cpk
  CPKs/ClientCommon.cpk
  CPKs/Common.cpk
  ...
```
共 122 项。**fs 层必须能读这些文件**，否则 `nn::fs::OpenFile` 会断言。

## 6. fs 层：符号级 HLE（Round 5–6）

domain 对象路线（`OpenFile` 回 `IFile` 对象）**行不通**：文件能打开、对象也返回了，
游戏仍在 `nn::fs::OpenFile` 断言。改为直接替换 `nn::fs` 公开 API，参数是普通指针：

| guest vaddr | 符号 | 行为 |
|---|---|---|
| 0x206eb0 | `nn::fs::OpenFile(FileHandle*,Pc,int)` | 打开 host 文件，写回 handle |
| 0x205700 | `nn::fs::CloseFile` | 关闭 |
| 0x205950 | `nn::fs::ReadFile(h,off,buf,size)` | `pread` 直接写 guest 缓冲区 |
| 0x205980 | `nn::fs::ReadFile(out,h,off,buf,size)` | 同上并回写字节数 |
| 0x205d50 | `nn::fs::GetFileSize(s64*,h)` | 返回真实大小 |

数据根：`/data/local/tmp/d3romfs`（已推 13GB；`/data/local/tmp` 是唯一 adb 可写且 app uid 可读的位置）。

### 两个坑

1. **`size` 下溢**：调用方用 `fileSize - offset` 算长度，offset 越界时下溢成 `0xFFFFFFFFFFFF0000`，
   `pread` 直接 EINVAL。已在 `fs_read` 里钳制并返回 0。
2. **进程静默退出不是崩溃**：无 tombstone、无 ANR、无 `fail()`、无 exit SVC ——
   是 guest 读不到合法 CPK 后自己走 fatal 分支。

### 当前数据缺口

游戏打开的第一个文件是 `CPKs/PVPCommon.cpk`，但：

- 基础 romfs（65 文件）没有
- 更新版补丁 romfs（37 文件，`Update/CPKs/Patch2_6_*/2_7_*`）没有
- 全部 18 个 NCA 的 fstree 都没有
- guest 里的字面量是 **`%s\CPKs\PVPCommon.cpk`**（PC 版模板，反斜杠）

结论：**guest 期望的数据版本与这份 XCI 提供的不一致**，需要确认 guest 的真实版本来源。

## 7. 突破点：fs 的 “path not found” 必须是 0xE02（Round 8）

反汇编 `main+0x22bc` 看到游戏对 `OpenFile` 结果的处理：

```asm
0x10022c8: bl  OpenFile(&handle, path, mode=1)
0x10022cc: cbz w0, ...            ; 成功 → CloseFile
0x10022d4: cmp w8, #0xe02         ; ★ 只有 0xE02 才当作「可选文件不存在」
0x10022d8: b.ne ...               ; 其他错误 → 改用 mode=3 去 Create → 断言
```

**`nn::fs` 的路径不存在是 `MAKERESULT(2,7) = 0xE02`，不是 0x7D402。**
之前一直返回 0x7D402，游戏不认识，走进 create 分支后断言 —— 这才是卡了很多轮的
`CPKs/PVPCommon.cpk` 之谜的真相：**它本来就是个可选文件**。

改对之后，游戏直接跳过缺失的 CPK 继续初始化。

## 8. 里程碑：guest 第一次发起 nvdrv 调用（Round 8）

```
sm:GetService name=nvdrv
sm:GetService nvdrv -> handle 0x100b
cmif port=nvdrv cmd=3  args=0x4000000
control nvdrv CloneCurrentObject
cmif port=nvdrv cmd=13 args=0x1
sm:GetService name=vi:m
sm:GetService name=vi:s
sm:GetService name=vi:u
```

从「卡在 time 的 0x2a2」到「打开 nvdrv 并发出图形命令」，全部由符号级 HLE 驱动，
hook 表共 **24 条**（time 5、socket 2、applet 1、fs rom 6、fs API 5、fs 写 5）。

## 9. 图形栈推进（Round 9+）

### nvdrv（`nn::nvdrv::INvDrvServices`）

| cmd | 名称 | 实现 |
|---|---|---|
| 0 | Open | 返回递增的假 fd |
| 1 / 11 / 12 | Ioctl / Ioctl2 / Ioctl3 | 接受并返回 0 |
| 2 | Close | 0 |
| 3 | Initialize | 0 |
| 4 | QueryEvent | 分配事件句柄 |
| 13 | SetConfiguration(u64) | 0 |

真机确认：`nvdrv::Initialize -> ok`、`nvdrv::SetConfiguration 0x1`。

### 显示服务（`nn::visrv`）

- `vi:m` = **IManagerRootService**，cmd 2 = GetDisplayService → IApplicationDisplayService
- `IApplicationDisplayService`：100 GetRelayService / 101 GetSystemDisplayService /
  102 GetManagerDisplayService / 1000 ListDisplays / 1010 OpenDisplay / 1011 OpenDefaultDisplay /
  1020 CloseDisplay / 1102 GetDisplayResolution / 2020 OpenLayer / 2030 CreateStrayLayer
- 本项目 SDK 版本里 **CreateStrayLayer 的编号是 2012**（不是新版的 2030）

真机确认：

```
IDisplayManager cmd=2 -> display session 0x100f
IApplicationDisplayService cmd=102 -> session 0x1010
IApplicationDisplayService cmd=101 -> session 0x1011
IApplicationDisplayService cmd=100 -> session 0x1012
IApplicationDisplayService cmd=1010 -> display id 1
IApplicationDisplayService cmd=2012 -> ok (stub)
Break(0) → nn::vi::CreateLayer (+0x2b4)
```

**当前阻塞**：`CreateStrayLayer` 必须返回 layer id + native window（parcel），
stub 返回空导致 `nn::vi::CreateLayer` 断言。这是接入真实图形栈的入口。

### Round 10：CreateStrayLayer 的 parcel 尝试

`IApplicationDisplayService cmd=2012` 现在是：

1. 从 CMIF 的 receive map descriptor 取缓冲区（`map_descriptor_size/address`）
2. 写入 parcel：`{data_size=0, data_offset=0, objects_size=4, objects_offset=0x10, objects[0]=<分配的句柄>}`
3. 回 `u64 layer_id = 1`

真机确认 parcel 确实写进去了：

```
CreateStrayLayer parcel -> 0x6d7ffff2e0 size 0x100 window 0x1013
IApplicationDisplayService::CreateStrayLayer -> layer 1
Break(0) → nn::vi::CreateLayer (+0x2b4)
```

**仍然断言**。反汇编 `nn::vi::CreateLayer`（0x3c9864 起）可以看到断言条件是
CreateStrayLayer 返回后 `[sp+0x18]` 的 unique_ptr 为空 —— 即 SDK 没能从 parcel 构造出
`nn::vi::Layer`。**native window 必须是真正的 HOS binder 对象**，伪造句柄不够。

这是图形栈的真正门槛：再往前需要实现 HOS binder + native window，
或者绕过 `nn::vi` 直接对接自有渲染后端。

### Round 11：越过 nn::vi::CreateLayer

从 `ParcelIo::OpenParcel`（0x3cc230）反汇编确认 parcel 头格式：

```
u32 data_size;       // [0]
u32 data_offset;     // [4]
u32 objects_size;    // [8]
u32 objects_offset;  // [0xc]
约束：data_size + objects_size + 0x10 <= size
```

我们的 parcel 本来就是合法格式，失败在更深处：`nn::vi::native::DeserializeNativeWindow`
（0x3cc020）在 `0x54c290` 解析失败时返回 **0x272**，holder 为空 → `CreateLayer` 断言。
那个对象是 **binder 支撑的 native window**，纯句柄值骗不过去。

**解法**：直接 hook `DeserializeNativeWindow`，把 holder 指向一块稳定的零填充块；
同时 hook `nn::vi::GetNativeWindow` 返回同一块。

真机验证：`nn::vi::CreateLayer` 的断言**消失**，guest 越过 layer 创建：

```
CreateStrayLayer parcel -> 0x6d7ffff2e0 size 0x100 window 0x1013
IApplicationDisplayService::CreateStrayLayer -> layer 1
vi: DeserializeNativeWindow -> dummy 0x6e0eadc728
```

之后 guest 不再发起 host 调用并静默退出（与 Round 6 同样的模式：无信号、无 ANR）。
下一步要么让 placeholder 具备真实 NativeWindow 语义，要么继续 hook 后续使用它的调用点。

### Round 12：整条 nn::vi layer 生命周期替换 → 进入 GPU 显存初始化

只替身 native window 仍然立刻静默死亡，于是把 `nn::vi` 的 layer 生命周期整体接管：

| guest vaddr | 符号 |
|---|---|
| 0x3c9830 / 0x3c9880 / 0x3c98a0 / 0x3ca080 | `CreateLayer` 四个重载 → 返回占位 layer |
| 0x3c9d10 | `GetNativeWindow` → 占位窗口 |
| 0x3c9c60 / 0x3c9c70 / 0x3c9da0 / 0x3c9e20 | ScalingMode / Crop / Position / Size |
| 0x3c9ea0 / 0x3c9f10 / 0x3c9fa0 / 0x3ca010 | Z / GetLayerZ / Visibility / Alpha |
| 0x3ca0e0 / 0x3ca150 / 0x3c6bf0 | Add/RemoveFromLayerStack、SetDisplayLayerStack |

真机结果（**重大推进**）：

```
vi: CreateLayer -> placeholder 0x6e133a30c8
vi: GetNativeWindow -> dummy
svc nvdrv::Open -> fd 256
MapPhysicalMemory addr=0x5576000000 size=0x4000000 rw
```

guest 现在会：创建 layer → 拿 native window → **打开 nvdrv 设备** → **映射 64MB 物理内存**
（GPU 显存初始化）。之后仍静默退出（无信号/无 ANR）。

还加了 PC 采样器（定时 SIGPROF 记录 guest PC），但这次死亡发生在 <100ms 内，没采到样本；
一旦出现长时间挂起，采样器会给出 PC 轮廓。

### Round 13：GPU 显存池与多线程

高频 PC 采样（5ms）只拿到 4 条，且 PC 全落在 **host 自己的 libc 区**（0x71c1...），
说明 guest 线程最后是在执行 host hook 里；之后既无退出 SVC、也无信号。

同一版本多次运行的死亡点**不一致**（guest 是多线程的）：

| 运行 | 最后事件 |
|---|---|
| A | `nvdrv::Open -> fd 256` → `MapPhysicalMemory 0x5576000000 0x4000000` → 死 |
| B | `vi::CreateLayer` → `GetNativeWindow` → 死（还没走到 nvdrv::Open） |

本轮观察到的显存池映射（SVC 0x2C）：

```
MapPhysicalMemory addr=0x552a000000 size=0x30000000   (768 MB)
MapPhysicalMemory addr=0x555c000000 size=0x17400000   (384 MB)
MapPhysicalMemory addr=0x5573800000 size=0x1000000    (16 MB)
```

这是 GPU 显存池初始化，说明 guest 已经进入图形内存管理阶段。下一步需要
`nvdrv` 的 ioctl 语义（通道配置）与 `nvmap`，并给 guest 线程加标识以理清多线程时序。

### Round 14：guest 线程真正跑起来了（重大修复）

发现 host 的 `svcStartThread`（0x09）**只打日志、从未启动线程** —— guest 创建的所有
工作线程都没执行过。这是多线程游戏的致命缺口。

修复：
1. `svcCreateThread(Handle* out, entry, arg, stack_top, priority, core)`
   —— 注意 **x0 是输出句柄指针**，入口在 x1、参数在 x2（之前误把 x0 当入口）
2. `svcStartThread` 真正 `pthread_create` 一个线程，调用 `guest_call(entry, arg, 0)`
3. 新线程以 TPIDR_EL0 = 0 启动（与内核行为一致），由 guest 自己的 trampoline 设置线程指针

真机验证：

```
CreateThread -> 0x1006
StartThread handle=0x1006 spawned
thread: start entry=0x6e102e8930 arg=0x6e10c7a000
svc #0x1a ... svc #0x1b ... svc #0x18 ...
WaitSynchronization count=0 handle=0xffffffff name= timeout=-1
```

新线程确实在执行 guest 代码并发起 SVC 了。

**新阻塞**：线程随后在 `WaitSynchronization` 上等待一个 **无效句柄 0xffffffff**，
进程随即退出。说明线程创建/同步对象（Event）的登记还有缺口。

### Round 15：事件对象原来是纯桩

`SignalEvent`(0x11) / `ClearEvent`(0x12) / `ResetSignal`(0x17) 之前只返回 0、不改任何状态，
`WaitSynchronization`(0x18) 也从不等待 —— 多线程下等于没有同步原语。

已实现：
- 每个事件句柄一个 `pthread_mutex_t + pthread_cond_t`（`CLOCK_MONOTONIC`）
- `SignalEvent` 置位并广播，`ClearEvent`/ResetSignal 清零
- `WaitSynchronization` 单句柄形式 `(handle, timeout_ns)` 真正阻塞，超时返回 `0xEA01`，
  成功后自动清除信号（与 Horizon auto-clear 语义一致）
- N 句柄形式保持原样（count=0 时立即返回）

真机现状：新线程启动后走到 `svc #0x18`，参数是**两个指针 + count=0**（N 形式、零句柄），
立即返回后线程不再产生 host 调用，进程随后退出。说明还有更靠后的逻辑问题。

### Round 16：线程标识 + 采样器安全性

1. 日志现在带线程 id（`t<tid>: ...`），能区分主线程与工作线程。
2. 采样器的 handler 改成**只写预分配环形缓冲**（异步信号安全），由独立 flusher 线程打印。

真机观察（thread 开启后）：

```
t27541: CreateThread -> 0x1006 ...
t27541: StartThread handle=0x1006 spawned
t27542: thread: start entry=0x6e0bbcc930
t27542: svc #0x1a ... (ArbitrateLock)
t27541: svc #0x1b ... (ArbitrateUnlock)
t27542: svc #0x18 WaitSynchronizationN count=0
t27542: WaitSynchronizationN count=0 handle=0xffffffff
```

主线程和工作线程此后都不再发起 SVC，进程约 3 秒后消失（无信号、无 ANR、无 crash dump）。

注意：**启用真实线程后，主线程的推进反而变短了**（从 1000+ 行降到 ~400 行），
说明线程同步把主线程挡住了。采样器这一轮还没采到样本（原因待查）。

### Round 17：WaitSynchronizationN 的 out_index 未初始化（已修）

解析调用点符号确认：

| SVC caller | 符号 |
|---|---|
| sdk+0x348464 | `nn::os::detail::MultiWaitImplByHorizon::WaitSynchronizationN` |
| sdk+0x349f90 / 0x34a074 | `InternalCriticalSectionImplByHorizon::Enter/Leave` |
| sdk+0x3489c4 | `ThreadManagerImplByHorizon::StartThread` |
| sdk+0x3487d8 / 0x348858 | `ThreadManagerImplByHorizon::CreateThread` |

反汇编 `WaitSynchronizationN(+0x24)`：结果是 0 时它**直接返回 `*out_index`**，
而 host 之前从没写过这个 out → guest 读到未初始化的栈值 → 后续行为不可预测。

已修：`count <= 0` 时写 `*out_index = -1` 并返回 `0xEA01`（TimedOut，
SDK 会映射成 -1）；`count > 0` 时写 0 并返回成功。

真机：日志变成 `WaitSynchronizationN count=0 -> timed out`，但工作线程之后仍然没有
后续动作。**count=0 本身很可疑** —— 说明 guest 在等一个空句柄列表，
很可能是线程启动时那个「已启动」事件没有被登记。

### Round 18：线程句柄可等待 + ExitThread

Horizon 里线程句柄本身是可等待对象（等待 = 等线程结束）。已补：

- `ThreadStart` 增加 `pthread_mutex_t + pthread_cond_t + exited` 状态
- `WaitSynchronization` 单句柄形式遇到 `D3_OBJ_THREAD` 时走 `thread_wait()`，
  支持超时（返回 `0xEA01`）
- `svcExitThread`(0x0A) 改为 `pthread_exit(0)`，不再触发 panic

真机：行为未变 —— 工作线程仍在 `WaitSynchronizationN count=0` 之后停止活动，
主线程也在同一时刻静止。进程约 3 秒后消失。

已确认 `d3_sync` 的互斥/条件变量实现是完整的（全局锁 + waiter 链 + tag 移交），
所以不是同步原语本身缺失。下一轮需要在 `d3_sync_lock/unlock/wait` 里加进出日志，
确认工作线程最后是否停在这些函数内部。

### Round 19：线程启动握手的实际时序

给 `d3_sync` 加了进出日志（`__android_log_print`，因为 `slog` 是 d3_service.c 的 static）。

真机时序（工作线程 = 后来的 t29653）：

```
thread: start entry=0x6e0e8ac930
sync: lock 0x6e0f23e1a8 tag=4102 blocks     ← tag=0x1006 = 工作线程自己的句柄
sync: unlock 0x6e0f23e1a8 tag=1             ← 主线程释放
sync: lock 0x6e0f23e1a8 woke result=0       ← 工作线程拿到锁
WaitSynchronizationN count=0 -> timed out
```

结论：**握手本身是成功的**（父线程创建→启动→子线程抢锁→父线程释放→子线程获得），
问题在于子线程拿到锁之后调用了一个 **count=0 的多等待**，然后就没有下文了。

SDK 的 SVC 包装器（0x3998fc）确认：`str w1, [x2]` 把索引写回 out，
即结果 0 时返回索引 —— 与 Round 17 的修复一致。

**当前最可疑点**：count=0 说明 guest 构造的等待列表是空的。这通常是更早某一步
（`AddMultiWaitHolder` 之类的登记）失败了，而不是等待原语本身的问题。

### Round 20：线程开关与 GPU 侧现状

加了 bring-up 开关：`<data_root>/notheads` 存在时 `StartThread` 不派发真实线程
（便于在主线程上推进图形侧）。

| 模式 | 日志行数 | 主线程到达 |
|---|---|---|
| threading 开 | ~405 | 线程握手后就静止 |
| threading 关 | 1043 | layer 创建 + 768MB/384MB/16MB 显存映射 + `nvdrv::Initialize`/`SetConfiguration` |

即便在 threading 关的情况下，guest 也**没有发出任何 nvdrv ioctl**，
在 `vi::GetNativeWindow` 之后就不再产生 host 调用并退出。

也就是说：图形侧的下一个真实调用点（`nvdrv` 的 `Ioctl`）还没被触达，
当前挡在前面的仍是「拿不到真实 native window 之后的行为」。

### Round 21：tombstone 定位到自己的 bug（重要）

用 Android 的 `dumpsys activity exit-info` 拿到官方退出原因：

```
reason=5 (APP CRASH(NATIVE)) status=11   ← SIGSEGV
```

再开代码里内置的 `no-handler` 模式（交给 bionic debuggerd），拿到带符号的栈：

```
#00 pc 0x1b600  libd3host.so (nvdrv_command+364)
#01 pc 0x18f24  libd3host.so (send_sync+6128)
```

**崩溃点在自家诊断代码里**：`nvdrv_command` 的 Open 分支为了打印设备路径，
把消息里所有"像指针"的字都当 C 字符串读 —— 而 `0x1006` 这类句柄值能绕过
`>= 0x1000` 的粗筛，读它就 SIGSEGV。已改用 `process_vm_readv` 安全拷贝。

修复后 `nvdrv_command` 不再崩，但**仍有另一处 SIGSEGV**（status=11），
且我们的 crash handler 依旧不落盘（selftest 崩溃能正常落盘，说明机制本身没问题，
怀疑故障线程的上下文特殊）。

### 诊断方法沉淀（后续一直有用）

| 手段 | 用途 |
|---|---|
| `dumpsys activity exit-info <pkg>` | 官方退出原因（SIGNALED/CRASH/LOW_MEMORY/ANR + status=信号号） |
| `<data_root>/no-handler` | 关掉自家 handler，让 debuggerd 出带符号的 tombstone |
| `<data_root>/selftest-crash` | 自测崩溃路径是否有效 |
| `<data_root>/notheads` | 关闭线程派发 |

### 关于 eden-emu

用户补充参考对象：**eden-emu**（Yuzu 系分支，Vulkan 后端，Android 原生）。
与 Strato 的差异：Yuzu 的 `video_core` 结构更清晰（`renderer_vulkan` /
`buffer_cache` / `texture_cache` / `shader_recompiler` 分层明确），
且其 Maxwell 命令处理与 Vulkan 后端边界比 Strato 更干净，可能更适合做移植基线。
