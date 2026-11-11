# 逆向过程与踩坑索引

本文归纳两条实现路径中已经遇到、后续仍可能重复的错误和排查方法；它不是新的进度表。具体构建、设备、实验数据及未完成项分别以 [Android 状态](../android/docs/STATUS.md) 和 [Windows 状态](../windows/docs/STATUS.md) 为准。历史证据只对记录中的游戏版本、二进制和测试场景成立。

## 路径和阶段

- **Android**：保留原始 ARM64 guest，在 Android ARM64 上执行；`android/host/` 接管 Horizon SVC/IPC、线程、TLS、内容和音频，nvdrv/GPFIFO 经 `android/gpu/host/`、Eden 的 Maxwell/shader 与 Vulkan 输出到 Surface。入口与约束见 [Android 架构](../android/docs/ARCHITECTURE.md) 和 [构建说明](../android/docs/BUILD.md)。
- **Windows**：固定版本的 ScarletNX 工作树通过 [补丁链](../windows/patches/README.md) 构建；SDL 输入进入运行时队列，随后由游戏线程调用原生世界动作和 UI，Vulkan 负责渲染与 FSR。代码分层和对象关系见 [KBM 代码地图](../windows/docs/KBM-CODE-MAP.md)，实际可用范围见 [当前交接](../windows/docs/HANDOFF-20261104-CURRENT.md)。
- **过程脉络**：10 月 16 日恢复 Android 宿主，处理启动、IPC、domain 与信号链；10 月 18 日接通 Eden、GPU 地址空间及首帧，并继续修复 guest 启动和同步；10 月 19 日起补宽屏和触控。10 月 21 日 Windows 建立 FSR 与补丁基线；10 月 31 日至 11 月上旬追踪 guest 运行时代码、UI 和原生键鼠。11 月 10–11 日继续验证两端场景/UI 分层，另评估 S2Arm 直连。提交记录给出阶段线索，某一阶段通过不表示全部游戏场景通过。

## 开始前：身份、输入和证据

1. **地址和对象有版本、进程边界。** 游戏 BuildID、原始 guest/模块哈希、运行时 exe 或 APK/SO 哈希、启动时间和 PID 要一起记录。重新启动后重新解析对象、UI 指针和实体 handle；不能只凭 PID 或旧 RVA 操作。Windows 探针入口见 [d3-re 说明](../windows/d3-re/README.md)。
2. **独立工作树不等于主仓库源码。** Android Eden 和 Windows ScarletNX 都被主仓库忽略；固定提交之外还有本地修改。先按对应依赖清单和有序补丁恢复，再验证补丁哈希和实际源码；不要把被忽略目录的空查询结果当作源码不存在。Windows 以 `base.json` 为准，不能把归档的 `0029/0030` 一起应用。
3. **安装包身份与源码版本分开。** Android 覆盖安装需要相同包名及签名；不同 profile 的私有数据、存档与驱动配置独立。当前某次日用包复用了旧宿主 SO，Java 源码或 APK 的变化不代表 native 也更新。安装前后逐项核对哈希，备份当前存档，不能卸载或清数据绕过安装确认。见 [Android 构建说明](../android/docs/BUILD.md)。
4. **证据链不能只留结论。** 保存同一构建和窗口的日志、截图、配置与业务前后值；`out/` 可清理，但先检查现有测试及汇总文件是否仍引用证据。游戏输入、密钥、签名和唯一存档留在 `local/`，不要放进可重建输出。

## Android：启动、服务与 GPU

1. **guest 构造、重定位与 TLS 不可猜。** 启动时重复执行初始化数组、丢重定位或错误处理线程本地寄存器，会造成后续看似无关的服务/图形崩溃。按实际模块布局和调用 ABI 定位，检查 BuildID、指令及 trampoline 空间，修改失败时不要部分写入。见 [架构约束](../android/docs/ARCHITECTURE.md)。
2. **崩溃处理本身也可能崩溃。** 历史上 handler 中使用 `dladdr` 导致再次故障、真正 fault 信息丢失；ART 和 guest 又共享信号链。先区分 guest 与 host/ART 线程，保留原信号动作和被中断的 TLS，必要时先输出不依赖复杂运行时的诊断；不能用吞信号或固定退出码掩盖故障。见 [信号链](../android/docs/architecture/SIGNAL_CHAIN.md)。
3. **IPC 不能把残留字节当参数。** HIPC 描述符数量会影响 CMIF 偏移；domain child 对象属于对应 session，普通标量、handle 和错误回复的对象数不能一律填 1。曾把旧回复残留 `args=0xe` 误当请求参数；应联合 `data_size`、头部和实际 buffer 判断。见 [时间服务与 domain 回复](../android/docs/architecture/TIME_SERVICE.md)。
4. **同步接口的假成功会延后崩溃。** 空 wait stub 可能让 guest 走到空链表或错误索引；零超时的返回值、释放 mutex、key hint 和其他寄存器均有语义。事件句柄关闭还要清理对应状态。离线 FIFO 子集通过不等于优先级继承、多线程及真实 guest 路径完整。见 [同步原语](../android/docs/architecture/SYNC.md)。
5. **HID 权限与内存区域要区分。** HID 共享内存采用服务端可写、guest 只读的双视图，直接写 guest 只读映射曾使 A 键崩溃。内存 SVC 的映射、权限、区域表排序和 QueryMemory 须使用一致快照，否则并发下会出现虚假重叠、查询空隙和启动 abort。
6. **有 Vulkan 设备或清屏不等于游戏出图。** GPU 地址空间要正确映射到设备内存，GPU 线程要启动，提交与 composite 的异步关系也要完整；空的 `PushGPUEntries` 或脱离 guest 的 `RequestComposite` 可能阻塞。先分别证明地址翻译、命令提交、同步和真实游戏帧，再验场景与 HUD。
7. **资源一致性不能靠跳过扫描换帧数。** CPU/GPU 双向修改、纹理别名与精确页快照必须维护；空置 dirty 回调会破坏画面。write-watch 早期存在 `mprotect` 已生效而 `Active` 尚未发布的首次布防竞态，另有扫描 CPU 下降但 FPS 变差的实测反例；保留精确审计并按同场景测正确性、等待和上屏。
8. **场景缩放与全屏超分是不同路径。** 匹配的场景附件可以降分辨率，而 UI/文字应保持目标尺寸；附件的物理像素范围、crop、usage、深度/模板和 Vulkan layout 都要一致。Mali 上已有线性回写场景通过的记录，但实验 EASU/RCAS 世界画面曾全黑，不能把标题或 UI 正常当作 FSR 成功。见 [Android 画质实验](../android/docs/BUILD.md)。
9. **系统能力不等于实际接入。** VRS 扩展、OEM VSR 进程/库映射或刷新率切换都不能证明游戏画面经过该路径，也不能证明生成帧、画质或节能。S2Arm 的 NVN 直连需要独立处理 guest ABI、资源别名、同步与 shader；留存包截图和当前复测失败属于不同证据。见 [迁移路线图](../android/docs/S2ARM-MIGRATION-ROADMAP.md)。

## Windows：从输入到业务动作

1. **静态 ELF、guest 运行时代码和 host JIT 不是同一地址空间。** 早期静态反汇编与运行时代码不一致，曾误判 UI handler；需要结合实际映射、运行时 dump、调用栈和当前构建的符号解析。源码按 [Windows 补丁链](../windows/patches/base.json) 重放后再查对应模块。
2. **键鼠不能只模拟摇杆或全局确认。** SDL 事件应按世界、游戏 UI 和运行时菜单分流，动作在游戏线程上执行；焦点、可见订阅者、模态 owner、按下/释放和键位冲突都要验证。中文输入法可能截获 `Q` 等键。实际键位和例外见 [操作说明](../windows/docs/KBM-INPUT-GUIDE.md)。
3. **高亮、回调返回和接受命令不是完成业务。** UI 视觉 setter 能改变高亮却不选中物品；`operate accepted` 不保证传送，提交技能不保证造成效果。需要 place、HP、资源/物品数量、技能状态或 UI 前后文本等可观察变化；覆盖取消与错误目标。历史 ABI 和负例见 [技术证据](../windows/docs/KBM-RE-EVIDENCE.md)。
4. **UI 控件看起来相同，控制器可能不同。** 商人用导航组 2，角色用组 0，工匠使用各自组与控制器；顶部页签没有 callback 也不意味着没有原生 selector。必须核对当前活动组、模式、订阅者和焦点，不能把成功的商人调用直接推广到工匠。列表要先选行再确认；多层模态按实际最上层处理。
5. **坐标空间和拾取对象容易混淆。** UI 安全区、引擎像素、实际窗口/DPI/黑边及世界坐标必须转换；历史 1280×720 时 UI x 常需加 160，不能硬套到所有窗口。射线点到怪脚可能命中地面；零半径秘境 portal 会被同位置方尖碑抢占；大碰撞体则可能在接近过程中卡住。比较同一帧的投影、碰撞、目标和实际状态。
6. **存档和场景前置条件影响结论。** “继续”可恢复进程中的旧会话，外部改盘后必须关闭进程再启动，否则自动存档可能覆盖新值；方尖碑坐标、场景实例、可用 DLC 和受伤/脱战状态也会改变结果。位置不同、物件不可交互或 `stopped` 不能当成功到达。
7. **串行探针，确认后台与进程身份。** 多个 Frida 进程并发 attach 曾导致游戏退出；新启动使用后台启动器，标题/CG 的 Space 跳过仅以出现主菜单为准，世界 HUD 出现后不能再当跳过键。每轮核对完整 exe 路径、启动时间和哈希，避免两个实例共用存档。
8. **渲染实验要管深度、资源寿命与后台呈现。** Windows 0145 的场景 FSR 包含附件识别、crop、格式、深度/模板同步和 GPU 使用期间的资源寿命处理；诊断 hook 本身有开销。非激活后台窗口的历史 Vulkan 停滞及高刷新率呈现问题要单独验证，不能把一个短窗或验证层无错误推广成长期稳定。

## 性能和验收口径

- 标题、过场、菜单、加载、城镇静置与持续战斗分开；guest/原生 composite、实际 Surface/上屏与 OEM 生成帧是三种不同计数。`present_us` 已包含部分等待，不能与子项重复相加；需要原始定义和时钟基准。
- 测量前固定构建、场景、存档、驱动、画质、亮度、温度、刷新率和后台状态。长短窗口、预热、诊断开销及同进程切换应记录；`/proc/uptime` 与 `CLOCK_MONOTONIC` 不能未经校准混用。
- USB 外部供电时不能据电池采样宣称放电功率或省电；ETW 权限不足时不能用提交帧率冒充实际显示。热状态、扫描耗时和降帧相关不自动构成因果。
- 构建、离线单测和标题画面各自只证明对应范围。每项功能记录前后业务结果；画质、长期帧率、功耗和音频听验单独验收。已通过的旧构建证据必须保留版本标记，不自动转成新构建已验收。
