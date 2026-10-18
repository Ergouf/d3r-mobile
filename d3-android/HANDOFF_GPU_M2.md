> **Start with [HANDOFF_CURRENT.md](HANDOFF_CURRENT.md)** — it is the short, self-contained state of
> the work (architecture, build/probe commands, current blocker, next steps).  This file is the
> long round-by-round history.

# GPU 栈接入：当前状态与交接（2026-10-18 09:00 更新）

## 已完成（真机验证）

- M0：Eden `video_core` + `shader_recompiler` + sirit 共 349 TU 编成 `libeden_gpu.a`（64.7 MB），
  `-Wl,--no-undefined` 通过
- 链接：`tools/build_host.py --with-gpu` 用 clang++ + 静态 libc++ 链入 `libd3host.so`
- M1：`vk_clear.cpp` 建交换链并清屏，真机截屏 `(40,88,209)`；证据 `gpu/probe/m1-clear-2026-10-18.png`
- 渲染器：`EmuWindowD3` + `GraphicsContextD3` → `Vulkan::RendererVulkan`，真机 `vendor=Qualcomm`
- 第一帧：`RequestComposite` 两次提交后经 BlitScreen/PresentManager 上屏，
  证据 `gpu/probe/m3-composite-2026-10-18.png`
- M2 基建：`Tegra::MemoryManager` 地址空间、`GPU::Start()`、C 桥
  （`d3_gpu_bridge_start/channel_id`）、GMMU `AllocateFixed + Map` 自检
  （`memtest: gpu=0x100000 translated=0x6c90000000 ok=1`）
- **guest 启动链已推进到 GPU 初始化**：`nninitStartup` → `_init_libc2` → `sdk DT_INIT` →
  `main DT_INIT`（游戏构造函数）→ 建 vi 会话（`vi:u`/`IDisplayManager`/`IApplicationDisplayService`）→
  `nvdrv::Initialize/CloneCurrentObject/SetConfiguration/Open`。
  证据 `gpu/probe/logcat-lock6.txt`（1067 行）

## 本轮定位并修复的四个根因（均有真机日志）

1. **hook 的 TLS 装错**（原先所有 `nn::diag::AbortImpl` 都死在 hook 里，看不到断言消息）
   hook 是 guest 代码直接 `br` 过来的，进入 hook 体时 `tpidr_el0` 仍是 guest 的；
   bionic 的 `__errno()` = `[[tp+8]] + 0x300`，guest TLS 该字为 0 → `snprintf` 在地址 0x300 崩溃。
   现在 `install_guest_hooks()` 给每个 hook 生成一个 0x60 字节 trampoline（host 内存，RX），
   换 host TLS、调用 hook 体、再换回 guest TLS，并记录 guest 返回地址与 guest `tpidr_el0`
   （`g_hook_tls`），所以现在能看到 `AbortImpl caller=sdk+0x…` 和断言字符串。

2. **CMIF 回复里的 handle 类别错**
   回复 special header 的 bit1..4 是 copy handle、bit5..8 是 move handle。
   `nn::sf` 的通用 client processor 读 copy 槽（`HipcMessageReader` [reader+0x44]），
   `nn::sm` 的 `GetService` 回复路径读 move 槽（[reader+0x48]）。
   原先一律写 bit5（move），导致
   - `ICommonStateGetter::GetEventHandle`（domain，copy）被读成 word0 = CMIF tag **6**
     → guest 去 `WaitSynchronizationN(6)`，host 不认识这个 handle；
   - 反过来把 copy 写死又会打断 `sm:GetService`（session 必须是 move）。
   现在 `reply_prepare_handle(..., category)`：`reply_handle`=move，`reply_domain_handle`=copy。

3. **`svcWaitSynchronizationN`（0x18）的 ABI 与返回值**
   本 SDK 是 `(s32* out_index, Handle* handles, s32 count, s64 timeout)` —— **timeout 在 x3**，
   不是 Horizon 文档里的 5 参数形式（x4 是垃圾）。旧代码读 x4，永远 `timeout=0`。
   另外 veneer 的 wrapper 会把 **x1 写回 `*out_index`**，所以宿主要在 x1 里给 index；
   旧代码没写 x1，SDK 拿 handle 指针当 index 去索引 holder 数组（`InternalWaitAnyImpl` 0x345d78 崩溃）。
   现在：按 x3 取 timeout，逐个 handle 轮询（事件/线程对象），成功回 `x0=0, x1=index`，
   超时回 `x0=0xEA01`；SDK 只接受 0 / 0xEA01 / 0xEC01，其它一律 `AbortImpl`。

4. **guest 线程没有自己的 TLS**
   宿主原来所有 guest 线程共用一个 TLS 块，而 SDK 把「当前线程 id」放在
   `[[tpidrro_el0+0x1f8]+0x1b0]`，并用它和互斥锁字里的 owner 比较
   （`nn::os::detail::InternalCriticalSectionImplByHorizon::IsLockedByCurrentThread`）。
   共用块让主线程读到 worker 的 id（0x1006），`SdkMutexType::Unlock` 断言 `this == NULL`。
   现在：每个 guest 线程一块 `0xC000`（TLS / TLR / thread 三页，16K 对齐，
   `GUEST_TLS_SIZE`/`GUEST_TLR_OFFSET`/`GUEST_THREAD_OFFSET`）；
   `svcCreateThread`(0x08) 为线程预分配，`guest_thread_body` 用它启动；
   `svcArbitrateUnlock`(0x1B) 的 owner 现在从当前线程 TLS 读（原来硬编码 1）。

5. **veneer 共享槽竞态**
   veneer 把 guest `tpidr_el0` 存到 table+0x10 再 `blr` dispatcher；两个 guest 线程会互相覆盖，
   导致 `tpidrro_el0` 解析到另一个线程的 region（进而另一线程的 thread id）。
   现在 patch veneer `base+0x3000090`：把 `cbz x17,#0x3000178` 换成 `ldr x3,[x16,#0x10]`，
   由 x3 把「发起 dispatch 的线程的 tpidr_el0」传给 `d3_hle_dispatch(kind, extra, saved, thread_tp)`。
   `svc #0x21`(SendSyncRequest) 的 message buffer 也用这条路径（每线程 TLR）。

### 第 5 轮：线程 TLS 解析修好（真机验证）

症状：引擎单例 getter（`main+0x10093d0` = `nn::os::GetTlsValue(slot)`）返回 NULL，
调用方在 `main+0x4c5cfc` 解引用空指针；之后又在
`InternalCriticalSectionImplByHorizon` 的 NULL thread object 检查上 abort。

根因有三个，全部修掉并真机验证：

1. **`guest_call_with_tp` 污染 TP 映射**：它原来把「guest 当前 `tpidr_el0`」直接登记成
   `tp → 自己`（`tp_map_add(tp, tp)` + `tid_map_set(tid, tp)`）。标题在 `main DT_INIT` 后把自己的
   线程指针指到模块 TLS（`0x552a1b3cc0` 这类地址），于是同一个线程后来会被解析回**标题自己的
   TLS 块**，`[tlr+0x1f8]` 读到 0 → 造出一个假 thread object → TLS slot 全空、临界区断言。
   现在登记的是「本线程自己的 host region」。
2. **映射解析没有校验**：新增 `g_regions[]` 记录本 host `mmap` 出来的 region，
   `guest_tlr_for_tp` 只接受落在其中的值，否则回退到 `this_guest_tls()`。
   验证：`SdkMutexType::Unlock` 日志从「`tp=0x552a1b3cc0 tlr=0x552a1b7cc0 thread=0x552a1bbcc0 id=0`」
   变成一致的「`tp=0x552a1b3cc0 tlr=0x71eba…9000 thread=0x6e0d…088 id=0x1`」。
3. **`SdkMutexType::Unlock` 不再调用 SDK 的 `Leave`**：改成 host 侧
   `d3_sync_unlock(mutex, guest_thread_id(tp))`。`Leave` 依赖 `tpidrro_el0` 指向的 thread
   object，标题改过线程指针后这条路径必然踩 NULL 断言。

证据：`gpu/probe/logcat-unlock3.txt`（tp map 里三个线程各一对 `game tp → host region`）、
`gpu/probe/logcat-tls18.txt`（解析一致性）、`gpu/probe/d3-crash-crash3.txt`（第 4 轮空指针现场）。

### 第 6 轮：`Leave` 断言修好（真机验证）

上一轮遗留的 `sdk+0x34a0a8` abort，这轮查清了**根因不是 NULL thread object**：
`InternalCriticalSectionImplByHorizon::Leave`（0x34a020）的实际代码是

```
0x34a038: w9 = ldaxr [x0]              ; 锁字
0x34a03c: cmp w9, w8                   ; 和我的 thread id 比
0x34a040: b.eq → 0x34a060              ; 是我的 → 直接清零
0x34a04c: tbnz w8, #0x1e → 0x34a070    ; 否则看 wait-bit
0x34a070: bl 0x399924                  ; svcArbitrateUnlock 包装
0x34a078: cbnz w0 → abort              ; ← 返回值非 0 就断言！
```

也就是说：**只要宿主 `svcArbitrateUnlock` 返回非 0，SDK 就 abort**。而我们的
`d3_sync_unlock` 原来在「锁字 owner != 调用者 tag」时返回 `SYNC_INVALID_STATE` ——
可 Horizon 的 `svcArbitrateUnlock` **从不失败**（不校验 owner，直接把锁字交给第一个 waiter）。
引擎里确实存在「新线程拿锁、父线程释放」的用法（线程启动握手），于是必然踩这个返回值。

修复：`d3_sync_unlock` 改成 kernel 语义 —— 检查到 owner 不匹配只记日志，
仍然 `sync_unlock_locked()` 释放并移交，最后返回 0。

真机验证（`gpu/probe/logcat-unlock4.txt`，1577 行）：`AbortImpl caller=sdk+0x34a0a8`
彻底消失，进程不再在 `Leave` 里死掉；随后是引擎自己的等待/退出流程。

### 第 6 轮新增的诊断能力

- **guest 栈回溯**：`hook_abort_impl` 现在会扫描 guest 栈里的返回地址并打印
  `stack[i] sdk+0x…/main+0x…`（`log_guest_stack`）。正是靠它看到
  `sdk+0x34a020 (Leave)` ← `sdk+0x529e3c (__nnmusl_MutexUnlock)` 的调用链。
- `nn::os::ExitProcess`(0x343100) hook：进程后来出现过「无信号、无 abort 直接消失」，
  用它确认是不是走了 ExitProcess（目前真机日志里该 hook 未被触发，说明不是这条路）。

### 第 6 轮结束时的阻塞

最新一轮（`gpu/probe/logcat-exit1.txt`）的 abort 变成 `sdk+0x34159c`，
即 `SdkMutexType` 的加锁包装断言 —— 也就是「锁字说这个线程自己已经持有，
却又来 Lock/TryLock」这类问题。下一轮从这里开始：把 0x34159c 的断言条件
（哪个 wrapper、比较什么字段）反汇编清楚，并检查 `d3_sync_lock` 在
「owner 是别的 tag 但 wait-bit 置着」时的行为。

### 第 7 轮：递归锁 + TLS slot 实现（真机验证）

1. **`sdk+0x34159c` 的身份查清**：它是
   `nn::os::SdkRecursiveMutexType::Unlock`（0x341540）里的
   `IsLockedByCurrentThread()` 断言，函数体是
   `assert(locked_by_me); if (--count == 0) Leave();`（word 在 +0，递归计数在 +4）。
   现在由宿主实现同样的语义（计数递减，归零时 `d3_sync_unlock`），**跳过 ownership 断言**。
   真机日志：`self=0x6e0f4cd938 count=2 word=0x1012 my_id=0x1012 caller=sdk+0x331b8c`
   → 再 `count=1 caller=sdk+0x331c50`，断言不再触发。

2. **`nn::os::GetTlsValue`/`SetTlsValue` 改由宿主实现**（TLS 数组位置
   `[[tpidrro+0x1f8]+0x80+slot*8]`），并加了 `tls: set/get` 日志。
   这直接暴露了一个**真正的并发 bug**：
   hook 里拿到的 guest thread pointer 来自全局 `g_hook_tls.guest_tp`，两个 guest 线程
   同时进 hook 时会互相覆盖 —— 日志里同一个 tid 上一行解析到 `thread=…3008 id=0x1012`、
   下一行解析到 `thread=…3248 id=0x1015`，于是 TLS slot 写到**别的线程的 thread object** 上，
   再读就是 0 → `[0+N]` 空指针。

   修复：`d3_hle_dispatch` 收到的 `thread_tp`（由 veneer 逐次传入，天然是当前线程的）
   记录到 **`__thread t_guest_tp_hint`**；所有需要 guest TP 的 hook 一律用
   `hook_guest_tp()`（优先该线程局部值）；`guest_thread_body` 启动时用本线程 region 预置。
   验证：worker 的 slot 0 现在写在自己的 thread object 上
   （`tls: set slot=0 value=0x552a1d3000 thread=0x552a1d3008 id=0x1012`）。

3. 试过但**放弃**的做法（记录避免重复踩坑）：在 trampoline 汇编里直接算
   `__thread` 变量的地址（`tpidr_el0 + offset`）。Android 上 dlopen 的库用 TLSDESC，
   该偏移不是常量，worker 线程上会算出野地址直接 SIGSEGV（fault 0x75cd565050）。

### 第 7 轮结束时的阻塞

主线程在 `tls: get slot=2` 时仍可能解析到 **worker 的** thread object（id 0x1015），
返回 0 后在 `main+0x898a10` 解引用 `+0x18` 崩溃。同时 `guest_thread_body` 里出现
「`start->tls` 与 `log_guest_region` 解析出的 region 不同」的现象
（`tls=0x71e8745000` vs `worker region tls=0x71e8762000`），说明**一个线程被分配了两个 region**。
下一轮把 region 归属做成单一事实源（以 `start->tls` 为准，禁止再分配），
主线程的 hint 也应在其启动时显式设置，而不是依赖全局回退。

### 第 8 轮：hook 的 guest TP 改为线程自有 region（真机验证）

第 7 轮留下的「主线程偶发解析到 worker 的 thread object」问题，这轮从根上切掉：
`hook_guest_tp()` 不再读任何共享状态（`g_hook_tls.guest_tp` 或 veneer 的共享表槽都会被
并发线程覆写），直接返回**本线程自己的 region**（`this_guest_tls()`）；
`guest_tlr_for_tp` 对 region 做恒等映射，所以这条路径永远落在同一个 thread object 上。

真机验证（`gpu/probe/logcat-tls23.txt`，1477 行）：

- `tls: get slot=… -> 0` 只剩两条（slot 29/30 在 set 之前的正常读取），
  不再出现「同一 tid 解析到两个不同 thread object」；
- 之前的 `fault=0x18`（TLS slot 为 0 后被解引用）崩溃 **消失**。

### 一个重要的排查经验：进程「静默消失」其实是崩溃

第 6/7 轮看到的「无 Fatal signal、无 abort、进程直接没了」，这轮确认是自己写的
crash handler 捕获了 SIGSEGV、写完 `files/d3-crash.txt` 后 `_exit`，
所以 logcat 里没有内核的 `Fatal signal` 行。**以后遇到静默消失先看
`run-as … cat files/d3-crash.txt` 的时间戳**，不要以为是 guest 调了 exit。

#### 第 9 轮：野跳转崩溃的寄存器级证据

第 8 轮末尾的崩溃（`gpu/probe/d3-crash-tls23.txt`）这轮把 dump 里的寄存器全看了一遍：

```
signal=0xb  fault=0x0  pc=0x48014cd4  lr/x30=0x48014cc4  sp=0x6e7c082610
x8=x9=0x762a0ba7bf1b40c1          # 形似栈 canary 的垃圾
x19=0xb4000070dd4aae40            # 带 top-byte tag 的 Android 堆指针
x22=0x020df4d8  x23=0x021392a0  x28=0x020df4d8  x29=0x020b6858
x27=0x00af2b2d74  x7=0x70451438  x15=0x00ebad6a89
host_sym=（空）                    # pc 不在任何已加载模块里
```

关键观察：

- `pc`/`x30` 都是 `0x48014cxx`，**不在任何映射区**，`dladdr` 也解析不出模块 →
  引擎跳到了野指针。
- 栈上出现 `0x020df4d8`、`0x021392a0`、`0x20b6858` 这类**小地址**，它们的量级
  正好是本 guest 镜像的大小（约 0x3182000）——像是**没加 load bias 的 guest vaddr**。
  如果把 bias(0x6e0e288000) 加回去，`0x020df4d8`→`0x6e2e1cd8`（镜像内，合法）。
  所以怀疑：某个值本来是 guest 镜像内偏移，却没被加上 bias 就被当成函数指针调用。
- `x8/x9` 是垃圾、`x19` 是带 tag 的宿主堆指针，说明那一刻寄存器状态已经被破坏，
  很可能是**更早的一次内存越界写**把栈/对象写花了，野跳转只是后果。

### 第 9 轮结束时的结论与下一步

这轮没有改代码：证据表明修不修 TLS 都只是表象，真正要查的是
「哪个对象被写花」或「哪个返回给 guest 的地址少了 bias」。下一轮按这个顺序做：

1. **审计所有 host→guest 的地址返回值**：`vi` 的 `CreateLayer`/`GetNativeWindow`/
   `DeserializeNativeWindow` 占位对象、`nvdrv::Open` 的 fd、`sm` 的 handle、
   `CreateTransferMemory`/`CreateSharedMemory` 的地址等，确认没有把
   「镜像内偏移」当成地址交出去；
2. 在 `d3_svc_*` 的返回值里加一条断言式检查：凡是「看起来像 guest vaddr 但不在
   `[bias, bias+image)` 内」的指针就记日志（能直接抓到少 bias 的那一处）；
3. 用 `sample` 采样器把**每个线程**的 PC 都记进 ring（现在只有一个线程的样本），
   这样野跳转前最后几条执行路径能留下来。

### 第 10 轮：HID 代理创建失败的路径查清（仍未修好）

第 9 轮怀疑「野跳转」来自某个对象被写花。这轮顺着 HID 这条线查
`nn::hid::detail::CreateHidServerProxy`（0x26b420，`SharedMemoryAccessor::Activate`
内部调用），定位到它失败在**发 IPC 之前**：

```
0x26b4d4: bl nn::sf::hipc::InitializeHipcServiceResolution()
0x26b4d8: x1 = "hid"
0x26b4e4: bl nn::sf::hipc::ConnectToHipcService(&handle, "hid")   ; 0x3789a0
0x26b4ec: bl nn::sf::hipc::FinalizeHipcServiceResolution()
0x26b4f0: cbz w20 → 继续 / 否则返回错误
```

`ConnectToHipcService` 只有两条路：

```
0x3789b8: bl nn::sf::hipc::GetPortProcessor("hid")     ; MITM 解析表
0x3789bc: cbz x0 → 0x3789e4                            ; 没有条目 → 直连
0x3789cc: blr [vtbl+0x28]                              ; MITM 路径
0x3789e4: x0 = NameHash("hid")
0x3789f8: bl nn::sm::GetServiceHandle(&handle, "hid", 0) ; 直连路径
```

而真机日志里 **只有一次** `sm:GetService name=hid`（引擎自己那次），
`CreateHidServerProxy` 全程没有产生第二次 sm 请求 —— 说明它走的是 MITM 路径
（`GetPortProcessor` 返回了非空条目）且该虚拟调用返回了错误，
或者 `sm::GetServiceHandle` 在拿到 sm 会话之前就失败了。

这也解释了为什么 `SharedMemoryAccessor::Activate` 必须被 stub：
**它现在返回成功但完全没有填 accessor 的映射地址**（我们只 `return 0`），
引擎后续读 npad 状态时读到的是残留指针 —— 这是第 9 轮「对象被写花 →
野跳转」最可疑的来源。

### 第 10 轮结束时的下一步

1. 给 `0x26b420`（`CreateHidServerProxy`）装一个**只记录**的 hook（不替换实现），
   打印它的返回值与被调用时机 —— 需要先解决「hook 无法调用原函数」的限制，
   做法：把 hook 装在它的**调用者** `0x2501e0`（Activate）里已经不行（我们 stub 了它），
   因此改为 hook `0x3789a0`（ConnectToHipcService）的**入口指令之前**不行；
   可行方案是 hook `nn::sm::GetServiceHandle`(0x379ce0) 并在里面打日志；
2. 真正实现 `SharedMemoryAccessor::Activate`：分配一块 256 KiB 零页，
   把指针写进 accessor 的映射字段（需要先把 0x2501e0 的字段偏移反汇编确认），
   让引擎读到「没有手柄」而不是垃圾指针；
3. 如果 2 之后野跳转消失，就说明第 9 轮的怀疑成立，可继续往 nnMain 后面推进。

### 第 10 轮（补）：`__thread` 在 hook 里不可靠 —— 这是 TLS 类崩溃的总根因

这一轮实测把最后一个未解之谜也定位了。日志（`gpu/probe/logcat-disp1.txt`）里
**同一个 boot 线程**（跑 `nnMain` 的 25881）在不同调用里解析出**三个不同的 region**：

```
t25881: call nnMain
t25891: thread: body tid=25891 tls=0x71e87b7000     ← worker 1
t25893: thread: body tid=25893 tls=0x71e8742000     ← worker 2
t25881: tls: get slot=30 -> 0 (region=0x71ebb3e000 tid=25881)
t25881: tls: get slot=3  -> 0 (region=0x71e87b7000 tid=25881)   ← worker 1 的 region
t25881: tls: get slot=2  -> 0 (region=0x71e8742000 tid=25881)   ← worker 2 的 region
```

原因：`this_guest_tls()` / `t_guest_tp_hint` 都是 **`__thread` 变量**，而 hook 的
trampoline 切到的是 `g_hook_tls.host_tp` —— 那是**一个全局字**，最后一次写它的是
任意一个跑过 `guest_call` 的线程。于是主线程的 hook 用了 worker 的 host TP，
`__thread` 读出来的就是 worker 的 TLS 块（→ worker 的 region）。
另外 `d3_hle_dispatch` 全程跑在 **guest TP** 下，那里读 `__thread` 会读到 guest 的
TLS 内容（通常为 0），`this_guest_tls()` 于是每次都新分配一个 region（这解释了
为什么主线程会「不断换 region」）。

**这一轮试过但没成功的三个方案**（保留记录）：

1. 宿主自己维护 TLS slot 表（按 region 键）→ 仍然 `fault=0x18`，因为 key 本身不可靠；
2. 在 `d3_hle_dispatch` 外层加 `g_in_dispatch` 守卫，让 `this_guest_tls()` 在
   dispatch 期间返回 0 → 只是减少了 region 泄漏，没解决 hook 侧错用 host TP 的问题；
3. hook `nn::sf::hipc::GetPortProcessor` 返回 0 强制走 `sm::GetServiceHandle` 直连
   → 没有改变 HID 的路径（`Activate` 已经被 stub，代理根本不会被创建）。

**正确修法（下一轮照这个做）**：

- 把 `t_guest_tls` / `t_guest_tp_hint` 从 `__thread` 换成
  **按 `gettid()` 索引的全局表**（`this_guest_tls()` 读表、首次分配时写表），
  这样与 host TP 无关，任何上下文都正确；
- 或者让 trampoline 切到**本线程自己的** host TP（需要每线程保存 host TP，
  且 asm 里无法用 TLSDESC，所以第一个方案更简单）；
- 顺带清掉：全局 `g_hook_tls.host_tp` 只在 `guest_call_with_tp` 里写，应改成
  每线程保存（`pthread_self()` 即 bionic 的 host TP，可在 C 里取）。

### 第 10 轮结束时的代码状态（重要）

当前源码里保留了本轮的三次尝试（TLS slot 表已换回第 7 轮的 thread-object 布局，
但 `g_in_dispatch` 守卫与 `GetPortProcessor` hook 仍在），能编译、能跑，
表现是 `fault=0x18`（`main+0x898a10`，`GetTlsValue` 返回 0）。
**已知最好状态是第 8 轮的 `build/apk-gpu-tls23`**（无 `fault=0x18`，崩溃是野跳转）。
下一轮如果先做上面「按 tid 索引」的修法失败，可以回退到第 8 轮行为再继续。

### 第 11 轮：两个真修复（真机验证）—— tid 键的 region 表 + `cntpct_el0` 陷阱模拟

#### 1. `__thread` 全部换成按 tid 索引的全局表

`t_guest_tls` / `t_guest_tp_hint` / `g_in_dispatch` 全部删掉，改成
`g_thread_regions[MAX_THREAD_REGIONS]`（`tid → region`，带 mutex），
`this_guest_tls()` 与 `thread_region_assign()`（`guest_thread_body` 启动时登记自己的 region）
都走这张表。这样与「trampoline 切到哪个 host TP」完全无关。

真机验证（`gpu/probe/logcat-tid1.txt`）：boot 线程（26155）的所有 TLS 操作
**只解析到一个 region**（`0x71ebb3e000`），不再出现「同一线程三个 region」。
`fault=0x18`（`GetTlsValue` 返回 0）这一整类崩溃消失。

#### 2. `mrs Xt, cntpct_el0` 在 EL0 被内核 trap（SIGILL）—— 已模拟

修完 TLS 后崩溃变成 `SIGILL(ILL_ILLOPC)`，dump 给出
`pc_off=0x33edf8`，反汇编：

```
0x33edf0: str xzr, [sp]
0x33edf4: cbz x1, 0x33ee58
0x33edf8: mrs x20, cntpct_el0     ← 读物理计数器，EL0 默认禁止 → SIGILL
```

这是 `nn::os::detail::TimedWaitLightEventImpl`（0x33edd0）在读当前 tick。
Android 用户态不允许读 `cntpct_el0`（`CNTKCTL_EL1.EL0PCTEN=0`），但**虚拟计数器
`cntvct_el0` 可以读**，而且频率相同。修法：在 crash handler 里识别
`(insn & 0xFFFFFFE0) == 0xD53BE020`（`mrs Xt, cntpct_el0`），
用 `mrs cntvct_el0` 取值写回 `Xt`、pc += 4，然后直接返回（不写 dump）。

真机验证（`gpu/probe/logcat-cnt2.txt`）：SIGILL 完全消失。
（第一版掩码写成 `0xD54BE020` 少算了一位，导致没生效 —— 已修正。）

### 第 11 轮结束时的阻塞

最新一轮的崩溃变成：

```
signal=0xb  fault=0x71f2a77768   pc=x30=0x71c172f184
x19=0x71f2a77740                 ← 正好是 host TP（bionic TLS）
```

即 guest 线程在**宿主代码**里执行、并且 `x19` 是 host TP，访问 `host_tp+0x28` 越界。
这与「hook/crash handler 里 TP 的切换与恢复」有关，下一轮先做：
1. 检查 `crash_handler` 的 counter 模拟返回路径有没有把 TP 恢复成 guest TP；
2. 检查 `guest_call_with_tp` 的 io[8]/io[6] 恢复逻辑在异常路径下的表现；
3. 用 `last_kind=1 / last_extra=0xa`（最后一次 dispatch 是 SVC #0xa=GetCurrentThread？）
   配合 ring 里的 `r_lr` 还原崩溃前的调用序列。

### 第 12 轮：veneer dispatcher 现在切回宿主线程指针（真机验证）

第 11 轮末尾的「pc 落在 bionic、`x19` 是 host TP、访问 `host_tp+0x28` 越界」查清了：
**`d3_hle_dispatch` 及其整条调用链全程跑在 guest 的 `TPIDR_EL0` 下**。
它里面调用的 `pthread_mutex_lock`、`info()`、`malloc`、`errno` 全是宿主 libc，
这些都要用 `tpidr_el0` 访问 bionic 的 `pthread_internal_t` —— TP 是 guest 的，
于是 bionic 读到垃圾结构并崩在 libc 里。

修复：

1. `g_thread_regions` 里新增 `host_tp` 字段（按 tid 索引，避免 TLS）；
2. `guest_call_with_tp`（本来就 `mrs` 出 host TP）、`guest_thread_body`、
   boot 线程初始化三处都登记 `thread_region_set_host_tp(...)`；
3. `d3_hle_dispatch` 入口：保存 guest TP → `msr tpidr_el0, host_tp` →
   跑 `dispatch_inner` → 恢复 guest TP。

真机验证（`gpu/probe/logcat-hosttp1.txt`，1555 行）：

- 之前那种「pc 在 bionic、x19=host TP」的崩溃消失；
- 引擎第一次跑到了**主循环**：`svc #0xb (SleepThread)` 带着递增的 x1 连续睡眠，
  另有 worker 正常 `ExitThread`（`svc #0xa`）退出；
- 但运行约 25 秒后仍然崩在一次 **fault=0x0、pc=0x480359ac** 的野跳转
  （`gpu/probe/d3-crash-hosttp1.txt`），和第 9 轮的 `0x48014cd4` 属于同一族
  （都是 `0x48xxxxxx`）。

### 第 12 轮结束时的阻塞与下一步

野跳转仍无解释，但已经排除了「host libc 在 guest TP 下运行」这条线。
`0x48xxxxxx` 这个地址族值得单独查：

1. 在所有 `blr`/`br` 类 hook（如 `nn::vi`、`nn::oe` 的回调）里加一条「目标地址不在
   `[bias, bias+image)` 就记日志」的保护，抓到跳转前的那个指针；
2. 检查我们交给 guest 的所有**回调表**（`vi` 的 `CreateLayer`/`GetNativeWindow`、
   NV 的 WSI 回调）是否被 guest 当成「含 vtable 的对象」使用；
3. 用 `d3-crash` 里的 `x19..x21` + `dump_memory_links` 追踪那个对象是谁分配的。

### 第 13 轮：野跳转的一个假设被证伪（veneer 返回路径）

第 12 轮留下的野跳转（`pc=0x480359ac`）这轮先验证「veneer 返回目标被写花」这个假设：

- veneer 的恢复段（0x3000130..0x3000174）结尾是
  `ldur x16, [sp, #-0x88]; br x16`，看起来很像能把 guest 送回一个花掉的地址；
- 于是在 `load_guest` 里把 `0x3000174` 的 `br x16` 换成 `brk #0x1234`，
  在 crash handler 里捕获该陷阱：打印 `x16`（目标）与 `x30`（调用者），
  目标高 32 位和 `bias` 不一致就记日志，然后照常 `pc = target` 继续。

真机结果（`gpu/probe/logcat-vret1.txt`，1656 行）：**没有任何 `veneer:` 日志**，
说明所有 veneer 返回目标都是合法镜像地址 —— **假设证伪**，
野跳转不是 veneer 返回路径造成的（这个陷阱机制保留下来了，后续还能复用）。

### 第 13 轮的新观察

最新 dump（`gpu/probe/d3-crash-vret1.txt`）：

```
fault=0x0  pc_off=0x480512ac  lr_off=0xaa712d98
x16=0x6e7c5182d0  x17=0x0  x19=0xb4000070dd4a2330  x30=0x6eb9eaad98
```

- `pc` 又是 `0x4805xxxx`（第 9 轮 `0x48014cd4`、第 12 轮 `0x480359ac` 的同一族）；
- 三次野跳转 dump 里 **`x17` 都是 0**，而 `x17` 正是 veneer 的间接调用/表指针暂存寄存器
  —— 强烈提示某处**通过空函数指针/空表项间接跳转**，`pc` 只是跳转后取指失败的残留值；
- `x19` 一直是带 top-byte tag 的 Android 堆指针（`0xb4000070dd4a....`），
  说明那一刻 guest 手里拿着的是**宿主堆对象**。

### 第 13 轮结束时的下一步

1. 把 `vi` 的占位对象（`CreateLayer` / `GetNativeWindow` / `DeserializeNativeWindow`）
   从「裸宿主指针」改成**带 guest 侧 vtable 的对象**：vtable 指向一段 guest 桩代码，
   任何虚调用都会先落到我们的日志桩上 —— 这会直接暴露「谁在拿这个对象做虚调用」；
2. 在 `nn::oe` / `nn::vi` 相关 hook 里记录返回值是否落在宿主堆（`0xb400...`），
   凡返回宿主堆指针的地方都加注释说明 guest 会怎么用它；
3. 如果 1 之后野跳转变成「桩代码日志」，就能定位到具体对象与调用点。

### 第 14 轮：野跳转现在有日志了（不再静默死亡）

第 13 轮留下的野跳转，这轮先在 crash handler 里加了两条处理：

1. **未重定位地址修复**：如果出错地址落在 `[0x10000, 0x40000000)`（镜像尺寸量级、
   但没有 bias），就当成「缺 bias 的 guest vaddr」，直接 `pc = bias + pc` 继续执行；
2. **野跳转记录 + 跳过**：`dladdr` 查不到模块、又不在镜像里时，打印
   `wild jump pc=… lr=… x0=… x19=…` 并把调用当成返回 0（`pc = lr, x0 = 0`）继续。

真机结果（`gpu/probe/logcat-bias1.txt`，1688 行）：

```
wild jump pc=0x48430378 lr=0x4842c088 x0=0x6f6b1b68 x19=0xb4000070dd4a0760 (host+0)
wild jump pc=0x4842c0b0 lr=0x4842c088 x0=0x0        x19=0xb4000070dd4a0760 (host+0)
（随后重复同一组 pc/lr）
```

得到的结论：

- 野跳转的 `pc`/`lr` **都落在 `0x48xxxxxx` 这一族**（第 9 轮 `0x48014cd4`、
  第 12 轮 `0x480359ac`、本轮 `0x48430378`），既不等于镜像内地址、也不是缺 bias
  （镜像尺寸只有 0x3182000，而 0x48xxxxxx 是 1.2 GB）；
- `dladdr` 对它们返回 0 → 不在任何已加载模块里 → 那片内存本轮没有映射；
- `x0` 是**宿主堆指针**（`0x6f6b1b68`，和之前 dump 里的 `0x6f63d8e0` 同族），
  `x19` 一直是带 top-byte tag 的宿主堆指针 —— 可以确定那一刻 guest 手里拿的是
  **宿主对象**，然后从它（或它的表）里取了一个函数指针去调。
- `pc - lr` 在 0x6000 上下，说明 pc 不是随机垃圾，而是同一片区域里的另一个地址
  （像是「表基址 + 固定偏移」）。

### 第 14 轮的重大线索：野跳转地址是**被截断成 32 位的指针**

启动时把 `/proc/self/maps` 的 r-xp 区间打进日志（`gpu/probe/logcat-maps1.txt`）后确认：
`0x48xxxxxx` **不是任何已加载的可执行区间**（宿主 lib 在 `0x6e1df62000`、guest 镜像在
`0x6e0f7…`、boot.oat 在 `0x70c3…`），而野跳转的 pc/lr 恰好等于某些地址的**低 32 位**：

```
野跳转 pc = 0x48430378  →  0x6e0e48430378 的低 32 位
野跳转 lr = 0x4842c088  →  0x6e0e4842c088 的低 32 位
野跳转 pc = 0x480359ac  →  0x6e0e480359ac 的低 32 位（第 12 轮）
野跳转 pc = 0x48014cd4  →  0x6e0e48014cd4 的低 32 位（第 9 轮）
```

也就是说：某处把一个 64 位指针塞进了 32 位字段（或被 `uxtw` / `w` 寄存器运算截断），
guest 再拿它当函数指针调用，于是跳到一片未映射内存。
这解释了为什么 `dladdr` 查不到、为什么 `fault=0`、也解释了三次野跳转为什么都在 `0x48…`。

嫌疑点（按可能性排序）：

1. 我们交给 guest 的**宿主指针**：`vi` 的 `CreateLayer` / `GetNativeWindow` /
   `DeserializeNativeWindow` 占位对象（`g_vi_layer` / `g_native_window`）、
   `d3gpu` 的 buffer 地址；
2. 服务回复里把 64 位值写进 32 位槽（某个 `Out<u32>` 收到了指针）；
3. guest 自己的结构体用 32 位存对象指针（Nintendo 的 32 位进程习惯），
   而我们的地址（`0x6e0e…`）装不进去。

### 第 14 轮结束时的下一步

1. 给 `vi` 的三个占位对象改到**低 32 位可容纳的地址**（在 0x40000000 以下
   `mmap(MAP_FIXED)` 一小块），这样即使 guest 用 32 位字段存也不会截断；
2. 或者给它们一个 **guest 侧 vtable**（第 13 轮方案），让虚调用先落到日志桩；
3. 在 `d3_service` 的所有 `reply_*` 里加断言：写进「32 位参数槽」的值若 > 0xFFFFFFFF
   就记日志 —— 直接抓到截断发生的那一条回复。

### 第 15 轮：占位对象改为统一 arena（并修掉 CreateLayer 返回 NULL）

第 14 轮的「32 位截断」线索没有直接被证实，但顺着它查出一处真实缺陷：

- `vi: CreateLayer -> placeholder 0x0` —— `hook_vi_create_layer` 直接用 `g_vi_layer`，
  而它只在 `native_window_init()` 里初始化（那是 `GetNativeWindow` 才走的路径），
  于是**图层句柄是 NULL** 交给了 guest。这本身就可能让引擎后面拿到空对象。
- 修复：新增 `low_arena()`（尝试 `mmap(MAP_FIXED_NOREPLACE)` 到
  `0x20000000`，失败则退回普通 `mmap`），`g_vi_layer`/`g_native_window` 都从这块
  arena 里切 0x100 字节，并在 `CreateLayer`/`GetNativeWindow`/`Deserialize` 三处
  都先 `(void)low_arena();`。

真机验证（`gpu/probe/logcat-low3.txt`，1603 行）：

```
vi: placeholder arena at 0x71eff68000 (4 GiB reachable=no)
vi: CreateLayer -> placeholder 0x71eff68800     ← 不再为 NULL
vi: GetNativeWindow -> dummy
```

注意 arena **没能落到低 4 GiB**（`0x20000000` 那段在进程里已被占用，
`MAP_FIXED_NOREPLACE` 返回失败后退回普通 mmap）。所以「32 位截断」这条假设
还需要换更低/更空的地址再试（下一轮：`0x10000000`、`0x30000000`，
用前先读 `/proc/self/maps` 找一个真空洞）。

### 顺带生效的修复：未重定位地址会被自动修正

`wild jump pc=0x20d80c0 is an unrelocated vaddr -> 0x6e0d9200c0`：
第 14 轮加的「缺 bias 修复」真的触发并救回了一次跳转（把 0x20d80c0 修正成
bias+0x20d80c0 继续执行）。这说明 guest 里确实存在**不带 bias 的地址**在使用。

### 第 15 轮结束时的阻塞

主野跳转仍是 `0x48xxxxxx`：
`wild jump pc=0x480359ac lr=0x48059700 x0=0x6f63d8e0 x19=0xb4000070dd49eb90`。
结合本轮「CreateLayer 曾返回 NULL」这个发现，下一轮优先验证：

1. 其它占位/句柄是否也曾把 0 或宿主指针直接交给 guest（把所有 `hook_vi_*`、
   `nvdrv::Open`、`CreateLayer`/`Layer` 相关返回值列一遍，逐个确认非零且可用）；
2. 把 arena 真正放到低 4 GiB（用 `/proc/self/maps` 找空洞 + `MAP_FIXED`），
   再观察 `0x48xxxxxx` 是否消失 —— 这是判定「32 位截断」假设的关键实验；
3. 若仍未消失，就按第 13 轮方案给占位对象加 guest 侧 vtable，让虚调用落到日志桩。

### 第 16 轮：低 4 GiB arena 实验完成 —— 「vi 占位对象被 32 位截断」被排除

这轮把 arena 真正放到低 4 GiB：

- 新增 `find_low_gap()`：读 `/proc/self/maps`，从 `0x10000000` 向上找一块
  0x2000 字节的空洞，用 `MAP_FIXED` 映射；
- 真机结果（`gpu/probe/logcat-low4.txt`，1745 行）：

```
vi: placeholder arena at 0x4a000000 (4 GiB reachable=yes)
vi: CreateLayer -> placeholder 0x4a000800
```

占位对象现在**确实落在 4 GiB 以内**，但野跳转依旧出现 —— 说明
「vi 占位对象地址太高被 32 位截断」这个假设**被排除**（至少不是唯一来源）。

### 本轮的新观察：野跳转的 lr 落在宿主代码里

```
wild jump pc=0x4804f3dc lr=0x6eb9eaad98 x0=0x7042a2f0 x19=0xb4000070dd4fc970 (host+0xa9532d98)
wild jump pc=0x482f9d3c lr=0x6eb9eab064 ...
wild jump pc=0x48005c5c lr=0x6eb9eaad98 ...
```

- `lr` 是 **宿主地址**（`0x6eb9...`，不属于 guest 镜像），说明这次坏跳转是
  **从宿主代码发起的**（不是 guest 自己跳的）；
- `pc` 仍然在 `0x4800_0000 ~ 0x4830_0000` 这一带（约 3 MB 范围），
  而且现在这块低地址区域里已经有我们的 arena（`0x4a000000`），
  两者相邻 —— 需要确认 `0x48xxxxxx` 到底是不是 `0x6e0e_48xx_xxxx` 之类地址的低 32 位。

### 第 16 轮结束时的下一步

1. 在 `wild jump` 日志里补上 `dladdr(lr)`（宿主函数名 + 偏移），
   直接指出是哪个宿主函数在做这次调用（是 `guest_call`、某个 hook、
   还是 GPU 桥的回调）；
2. 若是 `guest_call`，就检查调用目标是怎么算出来的（是否被 32 位截断/未加 bias）；
3. 如果确认是某个 hook 把宿主指针交给了 guest，再按第 13 轮方案加 guest 侧 vtable。

### 第 17 轮：重大发现 —— 之前的「野跳转」其实是 **ART（Java 运行时）自己的页**

第 16 轮留下的 `0x48xxxxxx` 野跳转，这轮用 `dladdr` 查了调用者：

```
wild jump pc=0x4804f3cc lr=0x6eb9eaad98 caller=?+0 lib=/apex/com.android.art/lib64/libart.so
wild jump pc=0x482f873c lr=0x6eb9eab064 caller=?+0 lib=/apex/com.android.art/lib64/libart.so
wild jump pc=0x48005d8c lr=0x6eb9eaad98 caller=?+0 lib=/apex/com.android.art/lib64/libart.so
```

`0x48xxxxxx` 是 **ART 的 JIT 代码页**，`lr` 在 `libart.so` 里 —— 也就是说：
**我们进程级安装的 crash handler 一直在截获 ART 自己的 SIGSEGV**
（ART 用隐式空指针检查 + 自己的信号处理），把它们当成 guest 崩溃记了下来，
甚至用「跳过/修正」的方式改写了 ART 的执行流。

修复：crash handler 开头先判断「这个线程是不是我们的 guest 线程」
（查 `g_thread_regions` 表，无锁只读）：

- 不是 guest 线程 → 把信号原样交还给之前安装的处理器
  （`g_previous_signals[sig]`，SA_SIGINFO 就调它的 `sa_sigaction`，否则 `sa_handler`，
  都没有就 `SIG_DFL` + `raise`），完全按内核语义处理，不做任何「跳过」；
- 是 guest 线程 → 才走原来的计数器模拟/野跳转修复/崩溃 dump 逻辑。

真机验证（`gpu/probe/logcat-art3.txt`，1817 行 —— 目前最长的一次运行）：

- **`wild jump` 计数为 0**（之前每次运行都有十几条）；
- 引擎稳定跑到主循环：`svc #0xb (SleepThread)` 持续、worker 线程
  `WaitSynchronizationN(applet-launchable)` 正常轮询；
- 顺带把第 16 轮的「低 4 GiB arena」回退成普通 `mmap`：把 arena 用
  `MAP_FIXED` 塞进低地址空洞会侵入 **ART 的 JIT 空间**（Java 线程随即在
  0x0 上崩溃），而它要验证的「32 位截断」假设已经被证明不成立。

### 第 17 轮结束时的阻塞

最新一次运行约 25 秒后，**binder 线程**（`binder:29566_4`）在 `fault addr 0x0`
上崩溃：这次内核直接报了 `Fatal signal 11` —— 说明该线程的故障**没有**经过我们
的处理器（很可能 ART 在我们之后又重新安装了自己的处理器，或者这确实是 ART
自身在这个进程状态下的崩溃）。

下一轮：

1. 启动完成后打印一次 `sigaction(SIGSEGV, 0, …)`，确认当前生效的处理器是我们
   还是 ART 的（决定是否需要在我们之后重新安装）；
2. 若是 ART 的 → 我们的 handler 实际已不生效，之前那些「guest 崩溃 dump」
   可能都来自 ART 线程，需要重新审视哪些 dump 才是真正的 guest 故障；
3. 若 binder 线程崩溃是真实的 ART 问题 → 抓它的 tombstone
   （`adb logcat -b crash` / `dumpsys dropbox`）看是哪个 Java 调用炸的。

### 第 17 轮补充：binder 线程崩溃的真身 —— 是 **Java 方法**在 ART JIT 里崩溃

tombstone 拿到了（`adb logcat -b crash`）：

```
signal 11, fault addr 0x0, Cause: null pointer dereference
    x8  0000000000080002  x17 0000000000000000
    lr  0000006eb9eaad98  pc  000000004804f74c
backtrace:
    #00 pc 0x204f74c  /memfd:jit-cache (deleted) (offset 0x2000000) (android.os.Binder.execTransact+44)
    #10 libbinder  IPCThreadState::getAndExecuteCommand()
```

即：**一个 Java 方法（`Binder.execTransact`）在 ART 的 JIT cache 里空指针崩溃**，
不是 guest 崩溃。结合本轮「我们的 handler 之前一直在截获 ART 的故障」这个发现，
可以确定：**这个进程里 ART 的内存被我们写坏了**。

最可能的写坏来源：`nn::os` TLS slot 的实现 —— 我们把 slot 值写进
`[tpidrro+0x1f8] + 0x80 + slot*8`，而当 `[tpidr+0x1f8]` 是过期/别人的指针时，
这次写就落在任意内存里（进程与 ART 共享地址空间，JIT cache 恰好在那一片）。

### 第 17 轮结束时待落地的补丁（下一轮第一件事）

把所有 TLS slot 的存取**完全放在宿主侧**，不再写 guest 内存：

- 结构：`struct { uint64_t region; uint32_t slot; uint64_t value; } g_tls_values[256]`
  + mutex，键是 `this_guest_tls()`（现在是 tid 键表，稳定）；
- `hook_tls_set(slot, value)`：查/建 (region, slot) 项后保存；
- `hook_tls_get(slot)`：查表返回值，未命中返回 0 并记日志；
- 因为所有 TLS 访问都经过这两个 SDK 函数，行为等价，但**零 guest 写入**。

（本轮已经写好这段代码，但源码里的注释标记被改过、替换没生效，
下一轮从 `/* nn::os TLS slots` 这一段重新替换即可。）

### 第 18 轮：bisect 结果 —— 不启动 guest 时进程完全稳定

这轮先确认了第 17 轮留下的 TLS 假设**已经不成立**：源码里 `nn::os` TLS slot
早就是宿主侧表（`g_tls_slots[256]`，键 `(region, slot)`），根本没有写 guest 内存。
另外确认 alias 区是启动时 `mmap(0, 64 GiB, PROT_NONE)` 由内核挑地址预留，
不会和 ART 抢地址。

于是做了一个决定性的 bisect：**不带 `--ez autostart true` 启动 App**（guest 完全不跑）：

```
am start -n com.d3mobile.host.recovery/com.d3mobile.host.MainActivity
→ 25 秒后 pidof = 29945（进程活着）、无 D3Host 日志、无 Fatal signal
```

而带 autostart 的同一份 APK，25 秒左右一定会在 ART JIT 里崩一个 Java 线程
（`android.os.Binder.execTransact`，fault 0x0）。

**结论：ART 的崩溃是「跑 guest」引入的** —— guest 或我们替它做的写操作，
写坏了 ART 也在用的内存。缩小范围后可查的写路径只剩：

1. **hook 的出参写**：`hook_vi_*`（`*out = 占位对象`）、`hook_fs_*`、
   `nn::os` 的 `SetTlsValue`（已是宿主表，排除）；
2. **guest 自己越界写**：guest 的堆/栈都在我们 `mmap` 的区域里，
   但如果 guest 代码用错指针（例如那个「未重定位地址」），就会写到任意地方；
3. **`svcMapSharedMemory`/`MapPhysicalMemory` 的 `mprotect`**：只动我们自己预留的
   alias 区，排除。

### 第 18 轮结束时的下一步

1. 在 `hook_vi_*` / `hook_fs_*` 的出参写之前加**范围校验**：
   只允许写进 guest 镜像或 guest 记录在册的内存区间（`add_fixed` 的区间表），
   其它一律记日志并跳过 —— 这能立刻暴露「写飞到 ART 内存」的那一处；
2. 给 guest 的**未重定位地址修复**（`wild jump` 里那条 `bias + pc`）加上白名单：
   只修正落在镜像尺寸范围内的值（已做），并且修正后若目标仍不可执行就不要再改 pc；
3. 如果 1 之后 ART 仍崩，再考虑用 `mprotect` 把 guest 的堆区标成 PROT_NONE 之外的
   保护页做写越界探测（代价大，留作后备）。

### 第 19 轮：出参指针正常，但崩溃点在不同运行之间漂移 → 指向共享状态竞争

这轮把 `vi` 三个 hook 的**出参指针**打印出来（`hook_vi_create_layer` /
`hook_vi_get_native_window` / `hook_vi_deserialize_native_window`），
确认写目标都是合法的 guest 栈地址：

```
vi: CreateLayer out=0x6e12f1ff20 -> placeholder 0x71eff67800
vi: GetNativeWindow out=0x6e12f1ff10 -> dummy 0x71eff68000
```

所以「hook 出参写飞」这个假设也不是本轮崩溃的原因。

### 真正的线索：崩溃点在不同运行之间漂移

连续几次运行（同一份 APK）崩在**完全不同**的位置：

| 运行 | 崩溃点 |
|---|---|
| art3 | ART JIT `Binder.execTransact`（fault 0x0），约 25 秒 |
| out2 | `fault=0x1b1`（NULL thread object 类，`[[tpidr+0x1f8]+0x1b0]`），pc 跑出镜像 |
| 更早 | `wild jump 0x48xxxxxx`（ART JIT）、`fault=0x18` 等 |

这种「同样的输入、不同的崩溃点」是**并发竞争**的典型特征。当前代码里还有一处
明确的共享状态：**hook trampoline 用的宿主线程指针是全局的**

- trampoline 汇编里 `ldr x17, [x17, #8]` 取的是 `g_hook_tls.host_tp`；
- 而 `g_hook_tls.host_tp` 只在 `guest_call_with_tp` 里写，**最后一次写它的线程赢**；
- 于是线程 A 的 hook 可能切到线程 B 的宿主 TP，随后所有宿主 libc 调用
  （日志、pthread、errno、malloc）都在 B 的 TLS 上跑 —— 这正是会**破坏 bionic/ART
  内部结构**的那种错误，能同时解释 ART JIT 崩溃和 `fault=0x1b1`。

### 第 19 轮结束时的修复方案（下一轮落地）

把「切到宿主 TP」这件事从**汇编 trampoline** 移到**C 层**，从而能按 tid 查表：

1. trampoline 不再切 TP（保留 guest TP 进入 hook 体）；
2. 所有 hook 体统一经一个 C 包装：进入时
   `guest_tp = mrs tpidr_el0; msr tpidr_el0, thread_region_host_tp();`，
   退出时恢复 `guest_tp`；
3. 现有 hook 里有 5 参数的（`hook_fs_write_file`），包装必须用
   **寄存器级转发**（把 x0..x7 原样传给真正的 hook 体），不能只传 4 个参数；
   实现方式：让 trampoline 仍然直接 `blr` 到 hook 体，但把「取 host TP」的那两条
   指令换成 `ldr` 一个**由 dispatcher 在每次 dispatch 前写入的全局**，
   并在那里同时保存 guest TP —— 这样写入点紧跟在本线程的 dispatch 上，
   竞争窗口从「任意时刻」缩小到「同一指令序列」，且可用 tid 键表兜底。

### 第 20 轮：guest 内存布局已可视化（为「是否与 ART 抢地址」提供依据）

这轮加了一行 layout 日志（在 `prepare_memory` 末尾），真机输出：

```
layout: alias=0 cap=0 stack=0x6a3fe00000 region=0x71ebb3e000
MapPhysicalMemory addr=0x54e99ce000 size=0x4000   rw
MapPhysicalMemory addr=0x552a000000 size=0x30000000 rw    ← 768 MiB
MapPhysicalMemory addr=0x555c000000 size=0x17400000 rw    ← 372 MiB
MapPhysicalMemory addr=0x5573800000 size=0x1000000  rw    ← 16 MiB
```

- guest 栈区在 `0x6a3fe00000`，线程 TLS region 在 `0x71ebb3e000`；
- guest 自己 mmap 的三大块在 `0x552a000000`/`0x555c000000`/`0x5573800000`
  以及 `0x54e99ce000`，与 ART/bionic 的典型区间（`0x70xx…` 的 oat、
  `0x6exx…` 的宿主 lib、JIT memfd）**都不重叠**；
- `alias=0/cap=0` 是因为 alias 区要到 guest 查询 GetInfo 之后才被赋值，
  这行日志打在它之前（下一轮把日志挪到 alias commit 之后即可）。

也就是说：「映射覆盖 ART 内存」这条也基本可以排除 —— 剩下的最可能仍是
**hook trampoline 用全局宿主 TP** 造成的竞争（第 19 轮结论）。

### 第 20 轮结束时的下一步（竞争修复的具体落地）

1. 把 trampoline 的「切宿主 TP」改成「切到 `d3_hle_dispatch` 在**本轮 dispatch 开头**
   写入的全局」（`g_hook_host_tp` + `g_hook_guest_tp` 成对写入，写入点紧跟在本线程
   自己的 dispatch 上），并把 `guest_call_with_tp`/`guest_thread_body` 也写这两个
   全局 —— 竞争窗口从「任意时刻」缩小到「同一线程的相邻指令」；
2. 若仍崩，就把 hook 体改成「进入即用 tid 键表查宿主 TP 并切换」的 C 包装，
   用**寄存器转发**保留 5 参数 hook 的语义（trampoline 里 `blr` 到一个 8 参数
   的裸函数，内部再转调真正的 hook 体）；
3. 顺手把 layout 日志挪到 alias commit 之后，便于以后一眼确认 guest 的所有映射。

### 第 21 轮：dispatch 刷新宿主 TP —— 不足以消除随机崩溃（负结果）

按第 20 轮计划，先在 `d3_hle_dispatch` 开头把当前线程的宿主 TP 写回
trampoline 用的全局（`thread_region_host_tp()` -> `g_hook_tls.host_tp`），
把竞争窗口从「任意时刻」缩小到「同一次 dispatch 的几条指令」。

真机跑了 3 次（每次 25 秒，`build/apk-gpu-hosttp2`）：

```
run 1 crash=yes
run 2 crash=yes
run 3 crash=yes
```

三次都仍然崩溃 —— 说明**仅靠刷新写入点不够**，必须把「切宿主 TP」彻底做成
每线程正确的。

### 关键实现信息（下一轮照此落地）

统计了现有 hook 的参数个数：**只有一个 hook 是 5 参数**（`hook_assert_failure`，
而且它本身直接 abort），其余全部 ≤4 参数。因此可以做「C 侧统一包装」：

1. 改 trampoline 汇编：把 x0..x7 存进 0x40 字节的栈帧，然后
   `hook_shim(x16 /*body*/, sp /*&frame*/)`；
2. `hook_shim(void *body, uint64_t *regs)`：
   - `guest_tp = mrs tpidr_el0`；
   - `msr tpidr_el0, thread_region_host_tp()`（tid 键表，天然每线程正确）；
   - 以 8 个 `uint64_t` 参数的函数指针调用 `body`（多余参数被忽略，
     所以 5 参数的 `hook_assert_failure` 也能正确传参）；
   - 恢复 `guest_tp`，返回 body 的返回值；
3. trampoline 只需保存/恢复 x0..x7 与 x30，其余寄存器保持原样。

这样 hook 里的宿主 libc（日志、pthread、malloc、errno）永远跑在**本线程**的
TLS 上，竞争问题从根上消失。

### 第 21 轮结束时的阻塞

随机崩溃仍在（每 20~25 秒一次，位置漂移：ART JIT / `fault=0x1b1` / 野跳转）。
已确认的排除项：vi 占位对象地址、hook 出参指针、guest 映射与 ART 重叠、
TLS slot 写 guest 内存。剩下就是这条 trampoline 宿主 TP 的竞争。

### 第 22 轮：per-thread hook shim 尝试失败并回退（基线已恢复）

按第 21 轮设计，把 trampoline 改成「保存 x0..x7 → 调 `hook_shim(body, &frame)` →
shim 内切到本线程宿主 TP → 以 8 参数调用真实 hook 体」。结果**失败**：

```
signal=0x6 (SIGABRT)  fault=0x287b0000776f    ← guest 起来就 abort，日志只到 sm:Initialize
```

原因：trampoline 是**手写机器码**（`sub sp`/`stp`/`ldr 字面量`/`blr`/`add sp` 共 17 条指令
+ 4 个字面量），我漏算了字面量偏移与栈帧布局，生成出来的指令流不正确，
guest 一进 hook 就炸。

已**完整回退**到第 21 轮那版（验证过的）trampoline，并真机复验基线恢复：

```
run: 1658 行日志、引擎正常跑主循环、ArbitrateLock/Unlock 正常
     （约 22 秒后仍是那个已知的 binder/ART 崩溃）
```

### 第 22 轮的关键教训 + 下一轮的更简方案

手写 17 条指令 + 字面量太容易错。下一轮改用**只包装 4 参数**的极简 shim：

- 统计过：只有一个 hook 是 5 参数（`hook_assert_failure`，它自己会 abort），
  所以 `Shim5(body, a0, a1, a2, a3)` 足够覆盖其余全部 hook；
- 汇编只有 10 条指令，且不需要把参数写进栈帧：

```
stp x30, xzr, [sp, #-16]!    ; 保存返回地址
ldr x16, =body
mov x4, x3
mov x3, x2
mov x2, x1
mov x1, x0
mov x0, x16
ldr x17, =hook_shim5
blr x17
ldp x30, xzr, [sp], #16
ret
```

- `hook_shim5(body, a, b, c, d)`：`guest_tp = mrs tpidr_el0` →
  `msr tpidr_el0, thread_region_host_tp_fast()` → 调 `body(a,b,c,d)` →
  恢复 `guest_tp` → 返回；
- 5 参数的 `hook_assert_failure` 继续用旧 trampoline（它只需要前 4 个参数就能报错）。

另外，下一轮应先加一个**自检**：启动时把生成的 trampoline 前 4 条指令
以 `%08x` 打进日志，用肉眼/脚本核对编码，再上真机，避免再次白跑一轮。

### 第 23 轮：4 参数 shim 也失败 → 结论：trampoline 必须交给汇编器

第 22 轮复盘后改用「只包装 4 参数」的极简 trampoline（11 条指令 + 4 个字面量）：

```
stp x30, xzr, [sp, #-16]!
ldr x16, =body            ; 字面量在 word[16]
mov x4, x3 / mov x3, x2 / mov x2, x1 / mov x1, x0 / mov x0, x16
ldr x17, =hook_shim5      ; 字面量在 word[18]
blr x17
ldp x30, xzr, [sp], #16
ret
```

`hook_shim5(body, a, b, c, d)` 在入口 `mrs` 出 guest TP、`msr` 到本线程宿主 TP
（tid 键表无锁查）、调 body、恢复 guest TP。

真机结果**仍然失败**（`build/apk-gpu-shim2`）：日志只到 207 行，
`sm:Initialize` 之后 guest 就在 `fault addr 0x0` 崩掉。

说明问题不在这两条新增指令本身，而是「**用 C 语言手写机器码**」这条路根本不可靠
（字面量偏移、栈帧、编码细节任何一处错都会让 guest 一进 hook 就崩）。
已再次**完整回退**到第 21 轮那版 trampoline，真机复验基线正常
（`gpu/probe/logcat-revert2.txt`，1657 行，引擎在主循环）。

### 下一轮的正确做法：让汇编器生成 trampoline

1. 新增一个真正的汇编文件（如 `host/hook_stub.S`），写**一个固定 stub**：

```
hook_stub:
    stp x30, xzr, [sp, #-16]!
    adrp x17, g_hook_bodies
    add  x17, x17, :lo12:g_hook_bodies
    ldr  x16, [x17, x16, lsl #3]   ; x16 = 索引
    mov  x4, x3
    mov  x3, x2
    mov  x2, x1
    mov  x1, x0
    mov  x0, x16
    ldr  x17, =hook_shim5
    blr  x17
    ldp  x30, xzr, [sp], #16
    ret
```

2. 打补丁的 guest 函数只写**两条**指令：`movz x16, #index` + `b hook_stub`
   （16 字节的补丁区足够，且 `movz` 的编码极其简单：`0xD2800000 | (imm16<<5) | 16`）；
3. `g_hook_bodies[]` 是 C 数组，装每个 hook 的真实函数指针；
4. 构建脚本里把 `.S` 加入编���（`tools/build_host.py` 需要多接收一个源文件）。

这样所有机器码都由工具链生成，且只有一处 stub 需要正确一次。

### 第 24 轮：汇编 stub 已跑通编译，但「trampoline 页必须在镜像附近」这一步没解决

按第 23 轮方案落地了汇编 stub：

- 新增 `host/hook_stub.S`（工具链编码，不再手写机器码）：
  `adrp/add g_hook_bodies` → 用 x16 里的索引取真实 hook 指针 → 转发 x0..x3 →
  `bl d3_hook_shim5`（切本线程宿主 TP 后再调 hook 体）；
- `tools/build_host.py` 的 `HOST_SRC` 加入该 `.S`；
- C 侧新增 `g_hook_bodies[]`、`d3_hook_shim5()`、`thread_region_host_tp_fast()`、
  `write_branch()`、`patch_hook()`。

两次真机迭代暴露了**分支范围**问题：

1. 直接把 guest 函数补成 `b d3_hook_stub` → 失败：
   `hook stub out of branch range for 0x6e11982210`
   （guest 镜像在 `0x6e0f…`，宿主 lib 在 `0x6e1c…`，距离超过 ±128 MB）；
2. 改成「镜像附近放一页 trampoline，每项 `movz x16,#index; b d3_hook_stub`」：
   - `MAP_FIXED_NOREPLACE` 在镜像后面找不到位置，回退到普通 mmap 得到
     `0x71f871e000`（又超出范围）：`hook stub out of branch range for 0x71f871e004`；
   - 改成 `MAP_FIXED` 强制放镜像后面 → 进程立刻 SIGABRT
     （说明那块地址并不是空闲的，强占破坏了别的东西）。

已**完整回退**到第 21 轮那版（验证过的）trampoline，并真机复验基线正常
（`gpu/probe/logcat-revert3.txt`，1593 行，引擎在主循环）。

### 第 24 轮结束时的下一步

1. 用 `/proc/self/maps` 在 **`bias` 附近（±100 MB 内）** 找一个真正的空洞
   （第 16 轮写过 `find_low_gap()`，可以复用并改成在给定区间内搜索），
   再用 `MAP_FIXED` 放在那里 —— 这样两个分支都在范围内且不破坏已有映射；
2. 或者在**加载镜像时就预留**一块紧随其后的页（`reserve_size` 里加 0x1000，
   加载后 mprotect 成 RWX），从根上保证近；
3. 把 `.S` 重新接回构建，跑真机验证。

### 第 25 轮：在镜像后面预留 trampoline 页（改了两处算术，仍未通过）

按第 24 轮方案，在加载镜像时就为 trampoline 预留一页：

- `mmap(reserve_size + 0x8000)`（原来 +0x4000），保留
  `[base+reserve_size, base+reserve_size+0x4000)` 这一页，其余照旧 munmap；
- `install_guest_hooks` 里 `page = base + image_size`，先 `mprotect(RW)` 写入每项
  `movz x16,#index; b d3_hook_stub`，再 `mprotect(RX)`；
- 把 `host/hook_stub.S` 重新接回 `HOST_SRC`，hook 站点补 `b page_entry`。

两处算术 bug 都修掉了（munmap 长度写错 → `guest address trim errno 22`），
但仍然**在打印完 maps 之后静默 SIGABRT**（53 行日志，连第一条
`hook … at …` 都没有），既没有 `fail()` 消息也没有信号现场。

已**回退**到第 21 轮那版（验证过的）trampoline 与旧的镜像预留逻辑，
真机复验基线正常（`gpu/probe/logcat-revert4.txt`，1755 行，引擎在主循环）。

### 第 25 轮结束时的排查建议（下一轮）

静默 abort 且没有任何日志，说明问题很可能出在**日志/映射本身**而不是分支范围：

1. 在 `install_guest_hooks` 里加**逐步日志**（进入函数、mprotect 前/后、
   第一个 hook 之前），确认到底停在哪一步；
2. 检查 `mprotect(page, 0x4000, RW)` 是否真的成功（返回值 + errno 单独打印）——
   预留的那一页此时是 PROT_NONE，若它其实已被 munmap 掉，mprotect 会 EINVAL/ENOMEM，
   而我们的 `fail()` 日志可能因为 fd/缓冲区状态没落盘；
3. 若确认是「预留页没保住」，就改成在 `install_guest_hooks` 里直接用
   `mmap(MAP_FIXED)` 覆盖 `base + reserve_size`（此时那块已确定在镜像预留范围内、
   且已被 munmap，属于空闲）——比在 mmap 时多要一页更可控。

### 第 26 轮：基线特征化 + M1 证据刷新（真机截图）

#### 1. 三次基线运行的特征化（同一份 APK）

| 运行 | 日志行数（20s） | nvdrv ioctl 数 | 崩溃线程 |
|---|---|---|---|
| 1 | 1639 | 0 | `binder:3116_2`，fault 0x0 |
| 2 | 1647 | 0 | `binder:3470_3`，fault 0x0 |
| 3 | 1704 | 0 | `binder:3727_4`，fault 0x0 |

三次都是**约 20 秒后、在 binder（Java）线程上 fault 0x0**，且 `nvdrv::Ioctl` 至今为 0。
期间 guest 主线程在稳定跑主循环（`svc #0xb` SleepThread，x0=0xe4e1c0 / 0x1e8480，
即 15 ms / 2 ms 的帧间隔睡眠），各 worker 线程正常 `WaitSynchronizationN`。
说明：**引擎已经进入主循环，但还没有开始渲染初始化**（因此没有 nvdrv ioctl），
而进程最后被一个 binder 线程的 Java 崩溃带走。

#### 2. M1（清屏/合成出图）证据刷新

同一轮里抓了真机截图与 d3gpu 日志，确认 GPU 栈仍然健康：

```
d3gpu: vk-clear: swapchain 2484x475 format=37 images=4
d3gpu: vk-clear: presented image 0 result=0
d3gpu: renderer: Vulkan::RendererVulkan ready (vendor=Qualcomm)
d3gpu: channel: allocated and initialised (0xb400006f5d510078)
d3gpu: memtest: gpu=0x100000 translated=0x6c90000000 ok=1
d3gpu: composite: 640x360 framebuffer submitted (gpu=0x200000) layout=2484x475
```

截图 `gpu/probe/d3-m1-20261018.png` 里 SurfaceView 显示的是 GPU 合成的彩色斜纹
（前景是 App 自己的 UI 文本），即 **M1 里程碑（Vulkan 清屏 + 合成上屏）在真机上成立**。

#### 3. 本轮结论

- M0/M1 稳定可复现（每次启动都能出图）；
- 引擎已进入主循环（帧间隔睡眠），但**尚未进入渲染初始化**（0 条 nvdrv ioctl）；
- 进程约 20 秒后死于 binder/Java 线程的 `fault 0x0`，与 guest 主循环无直接关系。

#### 4. 下一轮方向

1. 先把 binder 线程崩溃的 **tombstone 前 3 帧**（`Binder.execTransact` 之前是谁调的）
   抓全，确认是系统回调（如 `onTrimMemory`）还是我们 Java 侧的问题；
2. 如果是系统回调 → 检查 App 的 Java 层是否在 guest 线程死亡后仍被回调
   （例如 `nativePresent`/Surface 回调）；
3. 若是 ART 内存被写坏 → 用第 25 轮的「逐步日志 + MAP_FIXED 预留页」把 per-thread
   宿主 TP 修复真正落地（这是唯一还没排除的共享状态）。

### 第 27 轮：修掉 HID getter 触发的 AbortImpl（真机验证）

第 26 轮看到的 binder 线程崩溃，tombstone 显示是**我们自己的 `hook_abort_impl` 在 abort**：

```
#00 abort+160 (libc)
#01 hook_abort_impl+124 (libd3host.so)
```

对应日志：

```
AbortImpl caller=0x… (sdk+0x25ed1c)
abort arg0 = "this == NULL"
```

`sdk+0x25ed1c` 反汇编后是 `nn::hid::GetNpadJoyHoldType()` 的断言分支：

```
0x25ecd0: … bl nn::hid::detail::GetNpadJoyHoldType(&out)
0x25ec9?: cbnz w0 → AbortImpl("this == NULL")     ; 细节调用返回错误就断言
```

根因还是那条 stub：`nn::hid::detail::SharedMemoryAccessor::Activate` 被我们直接
`hook_success` 掉，导致 HID 的 detail 调用全部失败，而这些 SDK 包装层一律
「错误 → AbortImpl」。

修复：把三个会走这条路的 getter 直接让宿主回答中性值（返回 0）：

```
{0x25ecd0, hook_success, "nn::hid::GetNpadJoyHoldType"},
{0x25ee10, hook_success, "nn::hid::GetNpadHandheldActivationMode"},
{0x25eeb0, hook_success, "nn::hid::GetNpadCommunicationMode"},
```

真机验证（`gpu/probe/logcat-hid4.txt`，1588 行）：这次运行里 `AbortImpl caller=…` 为 0 条，
也没有 `"this == NULL"`。（该 abort 是**间歇性**崩溃模式之一：第 26 轮三次基线运行里一次都没出现，
单独跑一次就抓到了；修掉后这条路径不再触发。

### 第 27 轮结束时的阻塞

修掉 abort 之后，剩余的崩溃变成「JIT 区间 + 未重定位寄存器」：

```
pc=0x48059d0c  lr=0x48057938   x17=0  x19=b4000070dd4a2330
x22=0x02171a30  x25=0x020b5580   ← 又是不带 bias 的镜像内偏移量
```

`0x4805xxxx` 是 ART 的 JIT 页，而 `x22/x25` 是 guest 镜像内的偏移 —— 两件事同时出现，
最可能的解释仍是「guest 拿到的某个地址少了 bias，跳到了 JIT 页所在的那片低地址区」。

下一轮：

1. 在 `hook_success` 这类**返回 0** 的 stub 上不要紧，但要检查**所有返回地址值的 hook**
   （`vi`、`fs`、`oe`）是否都已经带上 bias（已有 `bias + pc` 修正逻辑，但只对
   `0x10000..0x40000000` 生效 —— `0x48xxxxxx` 落在区间外，所以没被修正）；
2. 把「未重定位地址修复」的判定改成：**只要目标地址不可执行且低 32 位落在镜像尺寸内**，
   就尝试 `bias + (pc & 0xFFFFFFFF)` 与 `bias + (pc & 0x7FFFFFF)` 两种重建，选第一个可执行的；
3. 若重建后能跑，就说明 guest 侧确实在用 32 位截断过的指针，再去定位那个来源。

### 第 28 轮：排除 alias 预留过大 + 定位「引擎为何不出 ioctl」

#### 1. 实验：把 alias 预留从 64 GiB 改成 8 GiB

假设：64 GiB 的 PROT_NONE 预留会挤压 ART 的地址空间，导致 Java 侧拿到 null → NPE。
真机结果（`gpu/probe/logcat-alias8.txt`，1675 行）：

```
alias 683fe00000 exc 71f8719000
…约 25 秒后 binder 线程仍然 fault 0x0
```

**假设排除**（预留大小不影响崩溃），已把 `ALIAS_SIZE` 改回 64 GiB
（构建 `build/apk-gpu-alias64`）。

#### 2. 关键定位：引擎在「主循环里空转」，且 **从未发过 nvdrv ioctl**

这轮把引擎空闲前的最后动作按顺序列出来（`logcat-alias8.txt`）：

```
hid cmd=106（SetNpadJoyHoldType）
sm:GetService("nifm:u") → nifm:u cmd=3 / cmd=0 / cmd=5
CreateThread ×3 + StartThread（worker）
之后主线程只剩 svc #0xb（SleepThread 15ms/2ms）循环
```

也就是说：引擎在**完成 HID + 网络初始化、起了三个 worker 之后就不再推进**，
一直以帧间隔睡眠，而 `nvdrv` 只在早期 Open/SetConfiguration 过，
**一条 ioctl 都没有**。

结合第 2 轮我们就知道的事实：引擎的 NV 初始化路径上有一个函数
`0x43a9b0` 会解引用 `[[this+8]+0x1ab8]`，而那个子对象当时是 NULL，
所以我们一直用 `hook_nv_probe` **跳过**它。**跳过它 = GPU 设备/通道从未被建立**，
引擎自然不会发 ioctl，也就不可能进入渲染 —— 这解释了「主循环空转 + 0 ioctl」。

#### 3. 下一轮的核心任务（M2 真正的入口）

1. 反汇编 `0x42cf00`（写 `[x19+0x1ab8]` 的那段）与其调用者，
   搞清 `[this+8]+0x1ab8` 到底该由哪一步创建；
2. 在 `hook_nv_probe` 里给该字段补一个**宿主分配的占位对象**（低地址 arena，
   带自洽的 vtable/自指针），然后**不再跳过** `0x43a9b0`，让 NV 初始化继续跑；
3. 一旦引擎开始发 ioctl，就用已有的 `nvdrv::Ioctl#` 全参数日志收集命令表，
   按 Eden 的 `NvDevice` 语义实现 —— 这才是 M2「nvdrv ioctl 打通」。

### 第 29 轮（修正）：`0x43a9b0` 不是初始化，是**每帧都会走的提交路径**

这轮跑基线抓了一个关键事实：`hook_nv_probe`（0x43a9b0）在 22 秒里被调用
**至少 16 次**（日志上限 16），而且每次 `self`/`arg` 完全相同：

```
nv: probe self=0x553a0127a0 arg=0x6a7fdff370 device=0x6e112a3f28 sub=0
（重复 16+ 次）
```

结论要修正第 28 轮的判断：

- `device`（`[[self]+8]`）是一个**镜像内的静态对象**（`0x6e112a3f28`，bias 内）；
- `sub`（`[device+0x1ab8]`）始终为 0；
- 这个函数**每帧都被调用** → 它是「提交/呈现」路径，不是一次性初始化。

也就是说：**引擎其实每帧都在尝试提交渲染**，但设备对象上缺少 `+0x1ab8`
这个子对象（本该由 NV 初始化创建），于是这条路径每次都被我们跳过、
什么也没提交 —— 这才是「主循环空转 + 0 ioctl」的真相。

### 下一轮的具体做法（已缩小到一步）

`hook_nv_probe` 里已经拿得到 `device`，只需：

1. 用 `safe_write(device + 0x1ab8, &placeholder, 8)` 写入一个宿主分配的占位对象
   （放在 `vi` 的 low arena 里，`+0x10` 处指向自身，避免 `[[+0x1ab8]+0x10]` 崩）；
2. 观察下一帧：如果引擎不再走「sub==0」的分支（日志里 `sub` 变成占位值），
   说明它开始按「有设备」的路径往下走 —— 这时再决定是否**取消对 0x43a9b0 的 hook**，
   让真正的提交代码运行（它会顺着我们补的对象继续走，可能开始发 ioctl）；
3. 如果取消 hook 后又崩在别处，就按崩溃点继续补字段。

这条路径比之前「重建整个 NV 初始化」要小得多，而且已经有真机证据支撑
（16 次调用 = 每帧）。

### 第 30 轮：能把「状态」注入 guest 了（占位对象 + 恢复原函数）

这轮把第 29 轮的三步做出来了，并新增了一个**通用能力**：

#### 1. 新增能力

- `safe_write()`：通过 `process_vm_writev` 往 guest 内存写，地址不可信也不会崩；
- `g_hook_original[64][16]` + `restore_hook(vaddr)`：**装过的每个 hook 都能把原始
  16 字节写回去**，于是「先用 hook 准备好状态，再把真正的函数放回来运行」成为可能；
- `hook_nv_probe` 现在会：读出 `device = [[self]+8]`，若 `[device+0x1ab8]` 为空，
  就往里写一个宿主分配的**自指占位对象**（vi 的 low arena，前 64 个字都指向自己，
  浅层 deref 不会跑到野地址）。

真机验证（`gpu/probe/logcat-nvph5.txt`，1636 行）：

```
nv: probe self=0x553a0127a0 … device=0x6e1101bf28 sub=0
nv: probe placeholder 0x71ebfa6200 -> [0x6e1101bf28+0x1ab8]
nv: probe … sub=0x71ebfa6200                  ← 下一帧就读到占位对象了
```

#### 2. 试过「恢复真实函数」：能过 NULL 检查，但撞到下一个未初始化对象

把 `restore_hook(base+0x43a9b0)` 打开后（`build/apk-gpu-nvph3`）：

- 真正的提交函数开始运行，**越过了 `[[device+0x1ab8]+0x10]` 的空检查**；
- 但随后在 `fault=0x6e138be9b0`（`bias=0x6e13484000` → **镜像内 +0x39B9B0**）
  崩掉 —— 即它去读/写一个**镜像内的静态对象**，那个对象本身还没初始化。

所以「占位对象」这一步是有效的，缺的是**镜像内静态表的某个字段**。

#### 3. 当前保留的默认行为

`g_nv_restore` 默认 0（保持「跳过 0x43a9b0」的稳定基线：1636 行、引擎持续跑），
把它改成 1 即可复现「真实函数运行 + 撞镜像内空对象」的现场（1140 行）。

### 第 30 轮结束时的下一步

1. 用 `d3-crash-nvph3.txt` 里的 `fault=0x6e138be9b0`（镜像内 +0x39B9B0）
   反查是哪张静态表/哪个字段（`pc_off` 是野地址，但 fault 地址在镜像内可用）：
   把 `bias + 0x39B9B0` 附近的符号/结构找出来，确认是不是 NV 设备/通道表的槽位；
2. 在 `hook_nv_probe` 里把该字段也补上（同样是自指占位或 0 以外的合法值），
   再打开 `g_nv_restore`，看是否继续推进或开始发 ioctl；
3. 一旦开始发 ioctl，用 `nvdrv::Ioctl#` 日志收集命令表，按 Eden 的 `NvDevice` 语义实现。

### 第 32 轮：确认「引擎拿到图层但从不呈现」

基线复跑（`gpu/probe/logcat-r32.txt`，1731 行，22 秒）：

```
nvdrv::Initialize -> ok
nvdrv::SetConfiguration 0x1
vi: CreateLayer -> placeholder
vi: GetNativeWindow -> dummy
nvdrv::Open -> fd 256
（之后只有 svc #0xb 的 15ms/2ms 睡眠循环）
nvdrv::Ioctl 计数 = 0
约 22 秒后 binder 线程 fault 0x0
```

关键点：

1. **图层链路是通的**：`vi:m` → `vi-app` 三个会话、`CreateLayer`、`GetNativeWindow`
   都成功；但之后**没有任何呈现类调用**（没有 `SetLayerImage`、没有 vsync 等待）——
   引擎拿到 native window 后就没有继续走向「present」。
2. 帧循环里的 `svc #0xb` 来自 `main+0x1006fb0` 这个**小助手函数**：
   `w8 = 0x0F4240 (1e6); umull x0, w0, w8; bl SleepThread`，即
   `SleepMilliseconds(ms)`，被 100+ 个位置调用 —— 它只是引擎的通用帧定时器。
3. 每帧真正被调用的是 `0x43a9b0`（我们跳过的那条提交路径，第 29 轮已确认 16+ 次/帧），
   而它依赖的 `[device+0x1ab8]` 我们已填入自指占位对象（`hook_nv_probe` 生效）。

### 结论

M2 的缺口非常具体：**引擎从未发起「创建 GPU 设备/通道」的 nvdrv ioctl**，
因此 `[device+0x1ab8]` 永远是我们补的占位对象，提交路径被跳过，
画面永远停在 M1（Vulkan 清屏合成）。

### 下一轮（剩余轮次里的建议顺序）

1. 打开 `g_nv_restore`（第 30 轮已实现）让真实提交函数运行，
   用 `d3-crash-nvph3.txt` 里的 `fault=bias+0x39B9B0`（SDK 段内的静态对象）
   反查该地址属于哪张表，补上缺的字段（现在有 `safe_write` 可以直接写）；
2. 若补完仍不发 ioctl → 引擎的 GPU 初始化被某个更早的失败 gate 住了，
   此时回到 `nn::oe`/`nn::vi` 的 hook，逐个把「返回错误」的调用找出来
   （在 hook 里打印返回值，凡非 0 的都记一条）；
3. M1 证据已齐（`gpu/probe/d3-m1-20261018.png` + `vk-clear`/`composite` 日志），
   M0/M1 可随时复现。

### 第 33 轮：`restore_hook` 修好（只读代码页），恢复后的真实提交路径暴露出下一层缺口

#### 1. 找到并修掉 `restore_hook` 的 bug

打开 `g_nv_restore` 后第一次运行，崩溃地址正好等于 **被 hook 函数自己的地址**：

```
fault=0x6e125b29b0   bias=0x6e12178000   → offset = 0x43A9B0
```

即 `restore_hook()` 往 `0x43a9b0` 写回原始字节时崩了 —— 因为镜像加载完成后代码段已经被
`protect_guest_segment` 设成 **只读可执行**。修复：写之前
`mprotect(page, RW)`、写完再 `mprotect(page, RX)`。

真机验证（`gpu/probe/logcat-restore3.txt`）：日志里出现

```
hook 0x6e0e8c69b0 restored to the real function
```

并且引擎继续跑了 1709 行（与基线 1773 行同量级），说明恢复动作本身成功。

#### 2. 恢复后的真实提交路径：又撞到一个未初始化的锁对象

恢复后下一次崩溃是 **guest AbortImpl**，位置：

```
AbortImpl caller=sdk+0x349fec      ← InternalCriticalSectionImplByHorizon::Enter 的断言
abort arg0 = "this == NULL"
```

即真实提交路径接着调用 `Enter(NULL)`（一个**未初始化的临界区/互斥对象**）→ 断言。
这与第 30 轮「镜像内静态对象未初始化」是同一条链上的下一层。

#### 3. 现状

- `g_nv_restore` 默认仍为 0（稳定基线：**1773 行、引擎持续跑、0 条 ioctl**）；
- 置 1 即可复现「真实提交函数运行 → `Enter(NULL)` 断言」的现场；
- `restore_hook` 现在可安全使用（这是本轮新增的可用能力）。

### 第 33 轮结束时的下一步

真实提交路径需要的是一个**已初始化的临界区对象**。两条路：

1. 在 `hook_nv_probe` 里把该临界区一起初始化：它是 `device` 或占位对象里的某个字段，
   只要把 `[device+0x1ab8]` 指向的占位结构里对应偏移填成一块**零ed 的可写内存**
   （临界区对象本身就是 {word, count} 形式，全 0 就是「未加锁」的合法状态），
   断言应能通过；
2. 或者按崩栈反查 `Enter(NULL)` 的调用点（`x0` 为 NULL 的那次调用在哪个 PC），
   直接补那个对象的指针。

第一条最省事：把占位对象的**更多偏移**填成「指向自身或零块」，让 `Enter` 拿到非 NULL
的临界区。下一轮先试这个。

### 第 34 轮：`Enter` 改由宿主实现 → 恢复后的提交路径跑得比以前远（1994 行）

第 33 轮恢复真实提交函数后撞到 `InternalCriticalSectionImplByHorizon::Enter(NULL)`
的断言。这轮把 `Enter` 整个改由宿主实现（与已有的 `Leave`/`svcArbitrateLock`
同一套锁字协议）：

```
Enter(cs):
  cs == NULL  → 记一条日志后当作「已获得」（引擎有些对象还没初始化）
  [cs] == 0   → 直接写入本线程 id（快速路径）
  否则        → d3_sync_lock(owner, cs, 本线程 id)   // 阻塞并在 hand-off 时拿到锁
```

挂载点 `0x349f30`。真机验证（`gpu/probe/logcat-enter1.txt`）：

- `Enter(NULL) tolerated` 没有出现（说明这次没有 NULL 临界区）；
- **日志 1994 行**（比上一轮的 1709 行更多），引擎在恢复后的提交路径上跑得更久；
- 崩溃从「`Enter(NULL)` 断言」推进到新的 **guest AbortImpl**：
  `AbortImpl caller=sdk+0x8abb0`（最近符号 `nn::aoc::ListAddOnContent` 附近），
  消息仍是 `"this == NULL"` —— 又一个未初始化的对象；
- `nvdrv::Ioctl` 仍为 **0 条**。

### 第 34 轮结束时的状态

- `g_nv_restore = 1`（默认打开）：走「真实提交路径」，能跑到 1994 行后撞
  `sdk+0x8abb0` 的 `this == NULL`；
- 宿主的 `Enter`/`Leave`/`svcArbitrateLock` 现在完全自洽（同一套锁字协议）。

### 下一轮

1. 用 `d3-crash-enter1.txt` 的 `x19/x20`（第 9 轮的 `dump_memory_links` 会打印
   对象链）定位 `sdk+0x8abb0` 是哪个对象为空；
2. 若它是 `device` 上的另一个字段，就接着用 `safe_write` 补；
3. 每补一层都要注意：**只有当引擎真正开始发 `nvdrv::Ioctl` 才算 M2 有进展**，
   所以这条链补完后要专门确认 ioctl 计数从 0 变成非 0。

### 第 35 轮：实现 `aoc:u` 服务，提交路径推进到 `nn::account::Initialize`（2070 行，最多）

本轮把 `Enter` 之后的断言一路往前推，并补上一个真实缺失的服务。

#### 1. `nn::aoc` 服务（新增）

第 34 轮末尾的 `sdk+0x8abb0` 断言，实际是
`nn::aoc::CountAddOnContent()` → `detail::GetObjectHolder()` 的代理调用返回错误 →
`AbortImpl("this == NULL")`。也就是说引擎在初始化内容/GPU 路径时会查询 DLC，
而我们没有 `aoc:u` 的服务实现（只在 `port_iface` 里映射了 `D3_IF_AOC`，
没有对应 handler，落到 `unsupported_command` → 错误）。

实现（`host/d3_service.c`）：

- `aoc:u` 新增 `PORT_AOC` 端口映射与 `aoc_command()`：
  - cmd 0 `CountAddOnContent` → 0
  - cmd 1 `ListAddOnContent` → 0 项
  - cmd 2 `GetAddOnContentListChangedEvent` → 分配一个事件句柄
  - 其它 → 成功 + 全 0 参数（避免 SDK 因失败而 AbortImpl）

真机验证（`gpu/probe/logcat-aoc3.txt`）：

```
svc aoc::GetAddOnContentListChangedEvent -> 0x101d      ← 服务生效了
AbortImpl caller=… (sdk+0x4b4bc)                        ← 断言位置往后移了
日志 2070 行（此前最高 1994）
```

#### 2. 新的断言位置

`sdk+0x4b4bc` = `nn::account::Initialize()+0x16c`，消息仍是 `"this == NULL"`。
但日志里**没有** `account` 的服务请求 —— 说明它是在 `nn::account::Initialize`
内部、还没走到 IPC 就断言了（很可能读某个全局/对象为空）。

### 第 35 轮结束时的状态

- 累计补上的服务/能力：`hid`、`aoc:u`、`fs` 目录语义、`nn::os` TLS slot、
  `Enter`/`Leave`/`ArbitrateLock` 锁协议、CLONE/长任务等；
- 引擎现在能跑到 **2070 行**，卡在 `nn::account::Initialize` 的断言；
- `nvdrv::Ioctl` 仍为 **0 条**（M2 未达成）。

### 下一轮

1. 反汇编 `nn::account::Initialize`（`sdk+0x4b350` 附近）看 `+0x16c` 读的是哪个字段，
   大概率是「账号服务代理对象」为空 —— 那就把 `nn::account` 相关的
   `sm:GetService` 请求真正服务起来（先看它请求的服务名，日志里没有再考虑
   在 hosts 侧直接造一个代理）；
2. 继续用「断言 → 反查 → 补对象/补服务」的循环推进，目标仍是 **ioctl 计数 > 0**。

### 第 36 轮：`nn::account` 用「容忍码」放行 + 路径非确定性确认

#### 1. 关键发现：`nn::account::Initialize` 只容忍一个错误码

反汇编 `nn::account::Initialize`（`sdk+0x4b350`）：

```
0x4b3fc: blr [vtable+0xb8]        ; 账号服务调用
0x4b400: w8 = w0 & 0x3fffff
0x4b404: cmp w0, #0
0x4b40c: ccmp w8, #0x2C7C, #4, ne ; ← 只有 0x2C7C 被容忍
0x4b410: b.ne → AbortImpl
...
0x4b434: blr [vtable+0xc8]        ; 又一次调用，同样只容忍 0x2C7C
```

所以只要让账号服务的失败码是 **0x2C7C**，`nn::account::Initialize` 就不会断言。

实现：新增 `PORT_ACCOUNT`（匹配 `account`/`account:u`/`account:a`），
`account_command()` 对所有命令统一回 `0x2C7C`（并记日志）。

#### 2. 但本轮这一跑没走到那条路径

本次运行（`gpu/probe/logcat-acct1.txt`，1678 行）里：

- `nv: probe placeholder …` ✓、`hook 0x43a9b0 restored` ✓（恢复路径走了）；
- 但**没有** `account cmd=`、也没有 `aoc::`，也没有 `AbortImpl caller`；
- 最后仍是 **binder 线程 fault 0x0**（ART 侧）。

也就是说：恢复路径之后的断言位置**在不同运行之间会漂移**
（aoc → account → 或直接 ART 崩溃），这与我们此前发现的「共享状态竞争」一致，
也让「按断言逐个补」的策略变得低效。

### 第 36 轮结束时的状态

- 宿主侧新增：`PORT_ACCOUNT` + `account_command()`（统一回 0x2C7C）；
- 构建通过（`libd3host.so` 15466976 字节），包 `build/apk-gpu-acct1` 已装；
- `nvdrv::Ioctl` 仍为 0 条。

### 剩余轮次的建议（务实收敛）

1. 先把 **per-thread 宿主 TP** 的修复落地（第 22–24 轮卡在「trampoline 必须在镜像附近」，
   而第 25 轮已经证明可以「加载镜像时预留一页」，只是当时有个静默 abort 没查完）——
   因为「断言位置漂移」强烈提示竞争，修掉它才能让后续补丁稳定可观测；
2. 稳定后再沿 aoc → account → … 逐个补服务（每个都有明确的「容忍码」或「返回 0」写法）；
3. 里程碑证据：M0/M1 已齐（`d3-m1-20261018.png`、`vk-clear`/`composite` 日志），
   M2/M3 未达成。

## 第 8 轮结束时的阻塞

最新 dump（`gpu/probe/d3-crash-tls23.txt`）：

```
signal=0xb (SIGSEGV)  fault=0x0  pc=0x48014cd4  pc_off=0x48014cd4
```

`pc` **不在镜像里**（bias=0x6e0e288000，合法地址都带这个前缀），说明引擎跳到了一个
野函数指针（很可能是某个 vtable/回调没被初始化，例如我们 stub 掉的
`nn::hid::detail::SharedMemoryAccessor::Activate` 或 NV 初始化那一步留下的空对象）。
栈上也扫不到任何镜像内返回地址（sp 已经不可信）。

下一轮方向：
1. 在 crash handler 里额外 dump `x0..x30`（`d3_saved` 已有寄存器快照，直接写进 dump 文件），
   用 `x0`/`x19` 等寄存器反推是哪个对象；
2. 给 `nn::hid::detail::SharedMemoryAccessor::Activate` 换掉 `hook_success`，
   真正把 256 KiB 的 HID 共享内存映射进去（`CreateAppletResource` 已经把句柄交出去了），
   排除「HID 对象是空的」这条线；
3. 逐个复检本轮之前加入的 bring-up 旁路（`0x43a9b0` NV probe、`0x2501e0` HID accessor、
   `0x1002210` crash-info 回调），确认哪一个留下了空对象。

## 未完成（当前阻塞）

**当前状态（第 7 轮结束时）**：crash-info 死循环、线程 TLS 解析、`Leave` 断言、
`SdkRecursiveMutexType::Unlock` 断言都已修好；`nn::os` 的 TLS slot 现在由宿主实现（带日志）。
当前残留：主线程偶发用到 worker 的 thread object（一个线程被分配了两个 region），
导致 `GetTlsValue` 返回 0 后在 `main+0x898a10` 解引用 `+0x18` 崩溃。
下一轮：把 region 归属做成单一事实源（以 `start->tls` 为准，禁止二次分配），
并在主线程启动时显式设置 `t_guest_tp_hint`。

**历史记录（第 6 轮结束时）**：`Leave` 里 `sdk+0x34a0a8` 的断言已修好（根因是我们
`svcArbitrateUnlock` 会返回错误，而 Horizon 的该 svc 永不失败 —— 见“第 6 轮”）；
当时最新的 abort 是 `sdk+0x34159c`，第 7 轮查明是 `SdkRecursiveMutexType::Unlock` 的断言。

**历史记录（第 2 轮时的状态，保留）**：guest 第一次跑到 `nnMain`
（`gpu/probe/logcat-hid3.txt`，196576 行，其中 nnMain 从第 898 行开始）：

```
call nnMain 6e12084480
SetThreadCoreMask/SetThreadPriority(handle 0x1)
fs: OpenFile data:/CPKs/PVPCommon.cpk  -> failed errno 2   # 解包出来的 romfs 里没有这个文件
fs: OpenFile data:/build.dat           -> failed errno 2   # 同上
CreateTransferMemory addr=0x1008 size=0x4000000
sm:GetService("nvdrv")                                    # 引擎自己在 nnMain 里取 nvdrv
CreateThread + StartThread (handle 0x1012)                # 引擎的 IO/加载线程
ArbitrateLock/Unlock 0x552a1d31b0                          # 正常 handoff
fs: OpenFile data:/CrashInfo.txt read -> failed errno 2
fs: OpenFile data:/_CrashInfo-0.txt ... -260163.txt ...    # 引擎陷入 19 万行、26 万次的自增重试
```

即：引擎启动后先找 `data:/CPKs/PVPCommon.cpk`、`data:/build.dat`（这两个文件在解包出来的
romfs/romfs_update 里**都不存在**），随后进入自己的 crash-info 写入流程，而
`data:/CrashInfo.txt` 的 `OpenFile(mode=1, 只读)` 在宿主上必然失败，引擎就把 `_CrashInfo-N.txt`
的 N 一路加下去（26 万次），整个启动被卡死在这个循环里。

**crash-info 循环已经反汇编清楚**（`main+0x1002240`，调用点 `main+0x10022cc`）：

```
0x10022b4: 名字由运行时 id 拼出（每次 +2~8，不是简单 n++）
0x10022c8: bl OpenFile(out, name, mode=1)          ; 只读
0x10022d0: w8 = result & 0x3fffff
0x10022d4: cmp w8, #0xe02                          ; 正是宿主返回的 D3_FS_NOT_FOUND
0x10022d8: b.ne 0x10022f4                          ; 不是 0xE02 → 走 rw
0x10022dc: w8 = 1                                  ; 0xE02 和“成功”都置 1
0x10022e4: (成功) CloseFile; w8 = 1
0x10022f4: bl OpenFile(out, name, mode=3)          ; rw（会创建）
0x1002304: 成功 → w8 = 2；失败 → w8 = 0
0x100230c: [x19+0x20]+0x38 = w8; return 1
```

即这个回调把状态写进 `[state+0x38]` 后返回；**调用方是间接调用**（BL 扫描找不到目标），
它用这个状态决定是否继续递增 id。70 秒跑到 `_CrashInfo-551397.txt`，说明循环实际无界；
`data:/CrashInfo.txt` / `_CrashInfo-0.txt` 是否存在都不改变行为（已实测）。

**下一轮最省力的定位法**：给 `0x1002240` 装一个 host hook，只记录 `g_hook_tls.guest_lr`
（hook stub 是 `bl` 进来的，这个 LR 就是**调用方返回地址**），拿到调用方后反汇编即可看到
循环条件与它依赖的状态，再决定 fs 语义怎么改。

其它两个观测：

- 引擎另有一个线程在 `WaitSynchronizationN(0x1013 applet-launchable)` 上永久等待
  （宿主从不 signal 这个事件），这是 applet 启动流程的缺口，GPU bring-up 不需要它。
- `data:/CPKs/PVPCommon.cpk`、`data:/build.dat` 在 XCI 解包结果里**确实不存在**
  （`reference/extract/romfs*` 都没有），引擎对它们的失败是可容忍的，不是根因。
- GPU 栈本身仍然健康（同一份宿主二进制）：`vk-clear: swapchain 2484x475 images=4`、
  `vk-clear: presented image 0 result=0`、`renderer: Vulkan::RendererVulkan ready (vendor=Qualcomm)`。

### 第 3 轮补充（当时仍未解决，第 4 轮已破解）

- 循环的 *驱动* 找到了：`main+0x1002010` 里 `ReadDirectory(&count, dir, ...)` 成功后
  `cbz w0 → 0x1002178`，然后按 `count` 遍历一个 **0x310 字节步长**的条目数组，
  每个条目通过 `blr x20` 回调（`main+0x1002210` → 探针 `main+0x1002230`）。
- 已经加了三个 host hook（**空目录**语义）：
  `nn::fs::GetDirectoryEntryCount`(0x205660) → 0、
  `nn::fs::OpenDirectory`(0x2071c0) → `0xE02`(path not found)、
  `nn::fs::ReadDirectory`(0x205550) → 0 条。**但遍历依旧发生**（105k 次探针），
  说明 count 不是从这三个调用拿到的，而是引擎自己维护的状态。
- 钩子安装位置要注意：`main+0x1002240` 只是探针*函数体中间*，
  真正的函数入口是 **`main+0x1002230`**（包装层 `main+0x1002210` 里的 `bl` 目标）。
  下一轮应当 hook `0x1002230` 和 `0x1002010`（打印 self/count/回调指针），
  就能确定 count 的来源与循环的终止条件。

M2 侧仍然待办（引擎跑起来之前 guest 不会发这些请求）：

1. `nvdrv::Open` 按设备路径区分 `/dev/nvhost-ctrl`、`/dev/nvhost-gpu`、`/dev/nvmap`；
2. `nvdrv::Ioctl` 已有参数全量日志（`g_nvdrv_ioctls` 前 80 条），但至今**一条 ioctl 都没收到**；
3. `vi: CreateLayer`/`GetNativeWindow` 还是占位对象，M3 要换成 `EmuWindowD3` 绑定。

### 第 4 轮：crash-info 遍历已破解（真机验证）

遍历的终止条件是**回调返回值**：`main+0x10021b8` 是 `tbz w0, #0`，回调返回 0 →
`w21 = 0` 并跳出循环；返回非 0 就继续下一个条目（0x310 步长）。

回调 `main+0x1002210` 是个通用 shim（`mov x0, x1; b 0x1002230`），从多个调用点进来
（`main+0x1005df0`、`main+0x1003e10` 等），条目里的 `name` 指针指向 guest 堆上的**未初始化内存**
（打印出来是空串/乱码 `" A*U"`），所以 `_CrashInfo-N.txt` 的 N 本身就是垃圾值 —— 也就是说
这个列表应该由某个没实现的读取填好，现在是空的/脏的，引擎才会走进“清理崩溃文件”死循环。

**修复**：在 shim 上装 hook，直接 `return 0`（“没有要处理的东西”），
真机验证 `_CrashInfo` 日志从 105,548 行降到 **0 行**，进程从“卡死”变成继续初始化。

修好后引擎的真实进展（`gpu/probe/logcat-crash3.txt`，1372 行）：

```
sm:GetService("hid") → hid cmd=101 / cmd=121          # HID 输入开始工作
nifm:u cmd=5                                           # 网络初始化
appletOE cmd=9
StartThread(0x1015) + SetThreadPriority/SetThreadCoreMask
worker: svc #0xb (SleepThread 1ms) 循环                # 引擎自己的调度线程
=> SIGSEGV fault 0x0  pc_off=0x14c5cfc (main+0x4c5cfc)
```

新崩溃点（下一条线索）：

```
0x14c5cec: x19 = &global[0x214a8d0]; x19 = *x19
0x14c5cf4: x0 = [x19]
0x14c5cf8: bl 0x10093d0          ; getter 返回 NULL
0x14c5cfc: ldr x8, [x0]          ; ← fault 0x0
```

即引擎的某个全局单例 getter（`main+0x10093d0`）返回 NULL，调用方直接解引用。
下一轮从 `main+0x10093d0` + 全局 `0x214a8d0` 入手，确认这个单例本该由哪个
初始化步骤创建（很可能与我们跳过的 HID accessor / NV 步骤有关）。

## 本轮新增的 bring-up 旁路（有注释，验证过能让 guest 继续启动）

- `{0x43a9b0, hook_nv_probe}`：NV 初始化里 `[[this+8]+0x1ab8]+0x10` 的空指针解引用，
  打印参数后跳过（该子对象由更后面的阶段创建）。
- `{0x2501e0, hook_success}`：`nn::hid::detail::SharedMemoryAccessor::Activate`。
  HID 的共享内存句柄在 `CreateAppletResource` 之后被 guest 当成 session 去
  `SendSyncRequest(0x1012)`（非 domain 回复的 handle 必须放在 **move** 槽，已改对，
  但 guest 仍把它当会话用），HID 输入对 GPU bring-up 不是必需的，所以先跳过。
- `hid` 服务：`CreateAppletResource`（cmd 0）返回 aruid=1 + 256 KiB shared memory，
  其余命令先回成功（`nn::hid` 对失败会直接断言）。


上一阶段遗留但已绕过/修好的问题（保留记录）：

- `SdkMutexType::TryLock`（sdk+0x3413b0）在对静态 applet 锁断言 —— 根因是
  `svcArbitrateLock` 的“递归判断”用错了身份：guest 传进来的 `x0` 是**锁字里当前的 owner**，
  真正的调用者身份是 `x2`(tag)。按 `x0` 比较会让第二个线程误判成“已经是我的锁”，
  两个线程同时认为自己持有同一把 SDK 锁。现在按 `tag` 比较，contended 时真正阻塞并在
  `svcArbitrateUnlock` 里把锁字交给 waiter 的 tag。
- `SdkMutexType::Unlock` 的 host hook 之前调错了地址（调成 `Enter` 0x349f30），
  现在调 `InternalCriticalSectionImplByHorizon::Leave`（0x34a020），并且用
  `guest_call_with_tp(..., g_hook_tls.guest_tp)` 保留 guest 当前线程指针
  （`main DT_INIT` 后 guest 会把 `tpidr_el0` 换成游戏模块自己的 TLS）。
- `guest_tlr_for_tp()` 现在会在发现 `[tlr+0x1f8] == 0` 时补一个合法的 thread 对象指针
  （内核本来保证这一点），否则 `nn::os` 在 `[tlr+0x1f8]+0x1b0` 上解引用 NULL（fault 0x1b0）。
- `nn::oe::SetupGpuErrorHandler` 被跳过（`hook_success`）：它注册的 system worker 的临界区
  在宿主侧没有初始化，会直接断言；GPU error event 本来也不会被 signal。


## 本轮新增的 host 侧行为（需要时可直接关掉）

- `{0x3413f0, hook_mutex_unlock}`：把 SDK 的 `SdkMutexType::Unlock` 换成
  “跳过 ownership 断言、直接调 SDK 自己的 `InternalCriticalSectionImplByHorizon::Leave`”。
  理由：Horizon 的 `svcArbitrateUnlock` 不校验 owner，SDK 的防御性断言在 host 上没有意义。
- `{0x33dfd0, hook_success}`：跳过 `nn::oe::SetupGpuErrorHandler`。
  SDK 会注册一个 system worker，其临界区在本 host 未初始化（NULL），会让 SDK 断言；
  GPU error event 本来也不会被 signal，bring-up 阶段先不注册。
- `d3_sync_lock`：递归判断改成 `(word & ~WAIT_MASK) == tag`。`tag` 才是调用者身份，
  `owner` 只是它从锁字里读到的当前 owner；按 `owner` 比较会让第二个线程误判成“已经是我的锁”。
- `svcArbitrateUnlock` 的 owner 改成从当前线程 TLS 读（原来硬编码 `D3_THREAD_ID=1`）。
- `hid` 服务（`PORT_HID`）：`CreateAppletResource`(cmd 0) 返回 aruid=1 + 256 KiB shared memory，
  其它命令先回成功。
- `reply_prepare_handle(..., category)`：**非 domain 回复用 move 槽、domain 回复用 copy 槽**，
  两者不能混（混了就退化成“读到 word0 = CMIF tag 6”，guest 会拿 6 当 handle）。


## 关键文件

- `d3-android/gpu/build_gpu.ps1`、`probe/coverage.ps1`、`tools/gen_shaders.py`
- `d3-android/gpu/host/{gpu_host,emu_window_d3,renderer_bringup,vk_bringup,vk_clear,nvdec_stub}.cpp`
- `d3-android/tools/build_host.py --with-gpu`、`build_apk.py`
- 真机取证：`d3-crash.txt`（`<private>/files/`）、`dumpsys dropbox --print`
- 符号/反汇编工具（本轮新增）：
  - `tools/dis_guest.py <so> <vaddr> [size]` — 按 vaddr 反汇编 guest（无 section header 也能用）
  - `tools/resolve_guest.py <so> <vaddr>` — GOT thunk → 真实地址 + 泄漏符号名
  - 用法示例：`python -I tools/resolve_guest.py …/libd3guest.so 0x547490`
- 本轮日志证据：`gpu/probe/logcat-tls{1..13}.txt`、`d3-crash-tls{2,3,6}.txt`、
  `d3-crash-handle2.txt`、`logcat-handle{2,3,4}.txt`

## 构建命令

```powershell
pwsh -File d3-android/gpu/build_gpu.ps1
cd d3-android
python -I tools/build_host.py --with-gpu --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime --private-root /data/user/0/com.d3mobile.host.recovery --output-dir build/host-gpu
python -I tools/build_apk.py --host build/host-gpu/libd3host.so --guest <libd3guest.so> --output-dir build/apk --keystore build/apk-gpu-waitn/local-debug.keystore
adb install -r build/apk/d3host-recovery-debug.apk
adb shell am force-stop com.d3mobile.host.recovery; adb logcat -c
adb shell am start -n com.d3mobile.host.recovery/com.d3mobile.host.MainActivity --ez autostart true
adb logcat -d -s D3Host:* > out.txt
```

注意：`build_apk.py` 每个 output-dir 会新建 keystore，升级安装必须复用同一个
`--keystore build/apk-gpu-waitn/local-debug.keystore`，否则签名不一致装不上。

## Round 2 progress (M2 still open)

Boot is no longer killed by the ART/JIT SIGSEGV and no longer dies in the account
authorisation assert; it now walks the applet framework and reaches the file
system.  Open issue: after the fsp-srv burst the guest goes silent and the process
exits by itself (ActivityManager: "has died: fg TOP", no tombstone).

Changes that made the difference:
- d3_host.c: the kernel SIGSEGV/SIGBUS/SIGABRT slot is no longer forced to our
  handler by default (file `files/d3-host-force-signals` re-enables it).  With
  libsigchain owning the slot ART resolves its own null checks in compiled code;
  forcing it turned every one of them into process death.
- d3_host.c: guest threads register `__builtin_thread_pointer()` instead of
  `pthread_self()` (bionic's pthread_t is not the TLS base).
- d3_host.c: two guest patches in `install_guest_hooks` neutralise the
  account-authorisation asserts (sdk+0x4c2f8 and sdk+0x4c328).
- d3_service.c: library applet framework (creator/accessor/storage), Controller
  applet result data (ControllerSupportResultInfo: 1 player, player 1, success),
  level triggered applet-launchable event, acc:u0 100/140/150/141/160, nifm:u
  commands 1/5/6/7, and `d3_hid_seed` which fills the Npad section of the hid
  shared memory (npad at 0x9A00, FullKey|Handheld, one wired pad).

Next steps:
1. Find out why the process exits right after the fsp-srv burst (hook
   `ExitProcess` logged nothing; capture full logcat, not only D3Host:*).
2. Get the hid block mapped (`MapSharedMemory` of 0x40000) so `d3_hid_seed`
   runs, then check whether the Controller-applet loop stops.
3. Then watch for the first `nvdrv::Ioctl` lines (M2).

## Guest image is a lossy repack: the original NSOs carry relocations it dropped

Measured with 	ools/nso_reloc.py (reads NSO0 sections + .dynamic directly, no
keys needed since eference/extract/exefs* is already decrypted):

| file | RELATIVE | GLOB_DAT | ABS64 | JUMP_SLOT (imports) |
|---|---|---|---|---|
| xefs/main.nso0 | 54098 | 8 | 228 | **342 named** |
| xefs_update/main.nso0 | (same shape, larger image 0x115ca14) | | | |
| libd3guest.so (what the host maps) | **87428** | 0 | 0 | 0 |
| xefs/sdk.nso0 | none found (no RELA table) | | | |

- The 236 symbol relocations are __cxa_pure_virtual (228 ABS64, the vtable fill)
  and __rel_dyn_start/end, __rel_plt_start/end (4 GLOB_DAT); all are *undefined*
  in main, i.e. supplied by the sdk module / rtld.
- __cxa_pure_virtual is at merged-image offset **0x4c7bd8** per
  eference/d3-symbols/sdk.symbols.json.
- The 342 JUMP_SLOT entries name every sdk/libc import main needs
  (
n::os::GetCurrentThread, 
n::time::Initialize, 
n::fs::MountRom,
  
n::mem::StandardAllocator::*, memcpy/memset/strlen, __cxa_guard_*, ...).
  Example slots: 0x10e4278 (`__nnmusl_init_dso`), 0x10e42b0 (`nn::time::Initialize`).
- All of those records are absent from libd3guest.so, which kept only RELATIVE
  entries: the SDK's own GOT/PLT slots are therefore never written, which is the
  mechanism behind "local" failures such as HID/1 at `sdk+0x25d614` and the
  0x20b abort at `sdk+0x8ff2c`.
- The symbols JSON is identical in eference/d3-symbols and
  eference/extract/exefs_update (25142 entries), so it is the best name table
  available; module build ids for matching are
  sdk `26ffb122262ca25e4c016c0af2f92a29483c64a2`,
  main `eafc2cef9b161d20514260d11266b5ae`.

### Next implementation step (rtld-style loader)

Load main.nso0 + sdk.nso0 directly instead of the repack and do what rtld does
(see switchbrew `Rtld`):

1. apply each module's RELATIVE records;
2. apply its JMPREL (R_AARCH64_JUMP_SLOT) and ABS64/GLOB_DAT records by resolving
   the symbol in the other module (st_value) or in the sdk module's exports;
3. patch `__rel_dyn_*` / `__rel_plt_*` to the table bounds of this loader.

Useful ready-made references gathered while searching: Skyline/Strato (Android
in-process ARM64 + HLE, same architecture as this host), Atmosphere
`stratosphere/*` (service semantics), Ryujinx `Hid.cs` (HID layout),
switchbrew `HID Shared Memory` + `Rtld` pages, and the nvhost/nvmap ioctl
definitions that ship with Android CTS / the FFmpeg tegra patches (for the nvdrv
ioctls needed by M2).

## Reference inventory (approved by the user)

| source | what it provides | how it is used here |
|---|---|---|
| **eden-emu** (local checkout eference/eden, commit e0d47f2 2026-10-16) | 37 files of nvdrv (
vhost_gpu/
vhost_as_gpu/
vmap/syncpoint/ioctl_serialization.h), 135 of hid_core (shared memory + Npad), 105 of m (library applets), 14 Android frontend files, 354 of ideo_core | GPU already built into uild/libeden_gpu.a; nvdrv ioctls for M2, HID layout and am applets from here first — it is the closest match to this host's design |
| Skyline / Strato | Android in-process ARM64 guest + HLE + nvdrv + Android input | later: input mapping, nvdrv path cross-check |
| Atmosphere stratosphere/* | service-side semantics (hid/am/account/ncm/fsp) | resolve "why did the service reject this" |
| Ryujinx Hid.cs, switchbrew *HID Shared Memory* | Npad shared-memory layout | already used to seed d3_hid_seed |
| Android CTS / FFmpeg tegra patches | nvhost/nvmap ioctl structs | M2 ioctl definitions |
| switchbrew *Rtld*, *NSO0* | module format + relocation rules | the loader work below |

Eden does **not** relocate modules itself: on a real boot the guest's own tld
module walks the loaded modules (scanning for MOD0) and applies the
RELATIVE/JMPREL/ABS64 records. That is why the merged single .so this host
maps — produced by a repacker that applied only RELATIVE — lost 578 records.

Merged-image layout (from d3-android/guest_layout.h): sdk at 0x10000, **main at
0x01000000**, veneer at 0x03000000. Cross-check: xefs_update/main.nso0 has
image size 0x115ca14 and the mapped .so's largest relocation offset is
0x215ca08 = 0x1000000 + 0x115ca08, so the guest was built from the **update**
modules and main(slot X) maps to merged offset  x1000000 + X.

### Loader fix, step 1 (next)

Generate a table {merged slot, merged target} from xefs_update/main.nso0:
slots = its 236 symbol relocations + 342 JUMP_SLOT records, targets resolved by
symbol name (__cxa_pure_virtual = 0x4c7bd8 in merged space per
eference/d3-symbols/sdk.symbols.json, 
n::*/libc names from the same JSON,
__rel_dyn_*/__rel_plt_* = this loader's RELA bounds). The host applies it in
load_guest() right after the RELATIVE pass. Step 2 is either keeping that table
or switching to booting the guest's real tld module.

## Round 3: the lost relocations are restored (loader fix landed)

	ools/gen_guest_relocs.py reads the **update** build's main.nso0, decodes its
dynamic table (8-byte header, then 16-byte entries: u32 tag, pad, u64 value),
resolves every non-RELATIVE record through the sdk symbol file (which is
**sdk-module-relative: add 0x10000**) and writes host/guest_relocs.h:

- 246 ABS64 slots -> `__cxa_pure_virtual` at merged `0x004d7bd8` (verified: the
  code there is the pure-virtual stub that prints and hits `udf`);
- 9 GLOB_DAT slots -> this loader's RELA bounds (`__rel_dyn_*`/`__rel_plt_*`);
- 529 JUMP_SLOT slots -> the sdk/libc exports the main module imports
  (`nn::time::Initialize`, `nn::os::GetCurrentThread`, `memcpy`, ...);
- **784 records, 0 unresolved**, applied in `load_guest()` right after the
  RELATIVE pass (log: `guest: applied 784 recovered relocations (0 out of range)`).

Effect on the device (probe `reloc3`): the boot now runs the real SDK start-up —
`call nninitStartup` / **`back nninitStartup`** (it never returned before) — and
then walks the service sequence (nvdrv opens, hid, account, fsp-srv, vi).  It now
stalls in guest code: watchdog reported `no svc for 1500 ms, svcs=283` with the
last dispatch returning to `main+0x1a378b0`, i.e. inside `main+0x68b0` (called
from `main+0x1a378ac`).  After that the process dies silently (no tombstone, no
host crash dump), which is the same silent-death pattern as before the fix.

Next: disassemble `main+0x68b0` to see what it loops on (a file/save wait is the
likely candidate, `fsp-srv cmd=51 -> fs not-found` is the last service call), and
find out why the process vanishes after the stall (ActivityManager log, not only
the D3Host tag).

## Round 4: mutex wait bit (d3_sync.c) and the next blocker

Root cause of the `main+0x68b0` stall: the guest's `nn::os::LockMutex` fast path is
a plain userspace CAS and its *unlock* fast path only takes the slow path when the
lock word carries Horizon's wait bit (0x40000000).  `d3_sync_lock` blocked without
setting that bit, so the unlocker just stored zero and never reached
`d3_sync_unlock`; the waiter slept forever.

Fix in `d3_sync.c`: `__atomic_fetch_or(mutex, D3_SYNC_WAIT_MASK, ...)` before
appending the waiter (`sync_unlock_locked` already hands the word to the first
waiter and clears the bit when none is left).

Device run `wmask3` (with the 784 recovered relocations): `nninitStartup` runs
and returns, the pctl/parental-control factory sequence completes
(`IParentalControlService::Initialize -> object 12 ready`), and the run now ends
in a *guest* AbortImpl instead of a hang:

    AbortImpl caller=sdk+0x3499c8  ("this == NULL!")
    = nn::os::detail::InternalConditionVariableImplByHorizon::Wait(InternalCriticalSection*)
      (sdk-relative 0x339950, symbol file offset 0x339950)

So the SDK's wait path now runs for real and finds a **null condition variable**
(the object was never initialised).  Next: find which nn::os object that wait belongs
to (event/semaphore/CV) and make the host's object initialisation write it, or hook
the wait and satisfy it from the event table.

Also this round: `build/libeden_gpu.a` had disappeared again together with
`build/host-obj`/`gpu-obj`/`apk-gpu-waitn` (cause unknown); rebuilt it with
`gpu/build_gpu.ps1` and re-created the keystore with `build_apk.py` (no
`--keystore`, then copy into `build/apk-gpu-waitn`).  The APK signature changed,
so the app was uninstalled and reinstalled once.
