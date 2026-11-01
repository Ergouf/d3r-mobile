# D3 原生键鼠：代码与实机 RE 方法评估

日期：2026-11-01，Asia/Shanghai。范围：Windows / ScarletNX。与 [方案](KEYBOARD-MOUSE.md)、[交接](KBM-HANDOVER.md) 一起阅读。只做原生键鼠，不开发或交付手柄映射。

## 1. 结论

原生 UI/动作层仍值得调查，但旧方法的证据质量不足以判断成功率。当前主要损耗来自地址换算、宿主/guest ABI 混淆、扫描提前停止和无法跨帧的实验输入。继续增加全局 hook、猜 handler 或重做代码基线，会重复消耗时间。

本轮实际完成：重启并激活 Serena；查阅运行时符号；Terra 启动游戏并做有限界面对照；Frida 读取当前进程、抓取段内容、观测 guest 方法和宿主按键；修复并验证静态引用扫描器。没有调用游戏业务函数，也未主动改写安装程序、配置或存档；未完成主菜单/城镇原生操作验收。

## 2. 新证据纠正了哪些旧判断

### 2.1 fixed ELF 与运行时内容一致，错误来自基址换算

当前安装 exe SHA-256：`254fb541e06b3490eaddb41f49da6ba4872b5e5604e0648a2e354f76784f3aba`。

code.dll SHA-256：`a829dce8ac2554a44df087132cf9d266582010280c660d32a958642c8b7bda51`。二者与原交接记录相符。

从 PID 13416 新抓取的段，与当前 `out/windows/kbm/b0/d3_main_fixed.elf` 对应节逐字节比较：

| 段 | 字节数 | 差异 |
| --- | ---: | ---: |
| text | 13,052,816 | 0 |
| rodata | 4,344,260 | 0 |

它们也与已有 `b2/runtime_text.bin`、`runtime_rodata.bin` 完全一致。因此“fixed ELF text 与当前代码不匹配”的旧结论撤回；不能继续据此否定原 ELF 或之前全部静态分析。

正确换算为 `guest - 0x8005000 = module offset`：

| guest 地址 | 正确模块偏移 | 旧比较误用偏移 |
| --- | --- | --- |
| `0x8366870` | `0x361870` | `0x366870` |
| `0x8a49690` | `0xa44690` | `0xa49690` |

前者在 ELF 和运行时里都以 `sub sp, sp, #0x160` 开始。旧比较按 `0x8000000` 而非模块真实基址换算，偏了 `0x5000`。重新导入 Ghidra 时沿用经过核验的 fixed ELF 即可，统一模块偏移和 guest 地址，不必再生成一套“不同代码版本”。

### 2.2 旧 hook 把 x64 宿主寄存器当成 ARM64 guest 寄存器

源码 `src/common/cpu/aarch64/cpu.h` 定义：

```c
typedef void (*GuestFn)(struct CPU* c, u64 entry);
/* CPU.x 在偏移 0；mem 0x350；disp 0x358；thread 0x378。 */
```

Windows 上截获的是 x64 重编译函数。Frida `args[0]` 是宿主 `CPU*`，`args[1]` 是 guest entry；原游戏 x0 必须从 `CPU.x[0]` 读取，控件字段再经 `g_mem + guest_pointer` 访问。

本轮观测到 UI 方法 guest `0x83baa90`：

- 4 秒内 327 次调用，解码错误 0；宿主 `Process.arch == x64`、`context.x0` 不存在。
- `context.rcx == args[0]`，并验证 `CPU.mem == g_mem`。
- 能读出有效 guest 对象、vtable、guest LR、TLS 和运行时线程指针。
- 本进程 UI 样本落在宿主线程 36652；宿主 `keymap` 在 16340。这个观察点不是已确认的鼠标消息入口，也不能证明所有 UI 工作只在该线程。

由此复核旧工具：

| 工具 | 问题 | 对旧结果的影响 |
| --- | --- | --- |
| `trace_ui_all.py`、`trace_ui_disp.py` | 读取 `this.context.x0/x1/...` | x64 上会报错；Python 消息处理忽略 error，HIT 输出可能丢失 |
| `trace_ui_vtable.py` | 先计数，再读不存在的 x0 字段 | 计数可能有效，寄存器采样无效；不能据此归因事件 |
| `trace_ui_widgets.py` | 把 `args[0]` 当 widget、`args[2]` 当配置 | 实际可能是在读 CPU 对象和无关宿主参数；“构造捕获到无效对象”需重审 |

所以“326 个 handler 全部零命中”“拿不到控件”只能保留为有缺陷工具下的历史观察，不能直接作为排除路线的证据。[Frida 官方 API](https://frida.re/docs/javascript-api/)区分目标架构的 CPU context 与函数参数，并提醒高频 JS 回调的成本。

### 2.3 原引用扫描只检查了 12 字节

旧 `xref_runtime.py` 未启用 skip-data。当前 text 头含嵌入数据，Capstone 在 guest `0x800500c` 停止：只解码 3 条指令、12/13,052,816 字节。旧代码还把 LDR 当三操作数指令，漏掉实际的内存操作数形式。

本轮修复：跳过不可解码数据并报告覆盖；处理 ADRP+ADD、ADRP+内存操作数、ADR 和直接 B/BL；限制页寄存器传播范围并在控制流边界清理；输出 JSON 供复核。

一次批量扫描三个目标的实测：

- 49.838 秒覆盖全部 13,052,816 字节；跳过 956 字节不可解码数据。这是线性扫描覆盖，不代表所有字节都是可执行指令，也不代替 CFG 分析。
- 找到 `LeftClickToMove` 地址的 1 处候选引用，以及 `0x83baa90` 的 11 处直接调用。
- 已用动态样本交叉验证：guest LR `0x83af070` 对应 `0x83af06c: bl #0x83baa90`。
- 另一动态 LR `0x8338d78` 对应 `0x8338d74: blr x8`。它属于间接调用，不能因为直接引用扫描未列出就认为没有调用。
- UI 管理全局 `0x914f840` 有 2,012 处候选引用，说明“找到全局后 hook 所有消费者”仍然噪声很大。

### 2.4 对象注册表有效，但不是可点击控件清单

标题/片头阶段注册表有 5,694 个条目。一次扫描并读取指定控件信息耗 11–12 ms，计数前后相同；这只是有限一致性检查，不是冻结线程得到的原子快照。

此阶段 `consolemainmenu_main` 已在注册表中，但画面并非主菜单。对象存在和矩形合理都不证明当前可见、可交互。继续利用注册表找到指定对象，追踪游戏自己的可见性、事件处理和命中规则；不要先遍历全部矩形再自行实现菜单点击。

第二次 4 秒观测采用 guest x0 对象过滤：720 次函数调用中，240 次匹配选定对象，保存 2 个样本且解码错误为 0。过滤减少了数据噪声，但 JS 仍进入全部 720 次；高频场景还需原生过滤或降低 hook 范围。

### 2.5 当前调用桥的安全性仍未成立

Serena 查到 `native_input_run` 复制 CPU、替换寄存器和栈，经 `snx_lookup` 执行；`rt_poll` 和 `snx_svc` 都可能消费队列。目前没有 UI 线程/帧阶段绑定，普通 `g_busy` 与共享栈也不能单独证明跨线程串行化。

超限或找不到函数后仍打印 returned。空参数返回没有业务效果，不能算原生动作成功。`SELFTEST_PC=0x8a49690` 的真实代码也不是注释所称的 djb2，保持禁用；这是错误函数定位，不能归因为本轮已被否定的“代码版本不同”。本轮没有执行这些业务调用。

## 3. 实际界面对照及边界

所有界面工作由 GPT-6.1 Terra 执行，使用 computer-use 技能。有效实验进程 PID 13416 的启动参数包含 `mouse_steer=0`、`touch=0`，未启用 native 自测。

1. 标题画面会在无输入时自动进入片头，界面过渡不能默认归因于最近一次按键。
2. 10:26:49.871–10:26:50.278，Terra 用 sky 发一次 Space；Frida 在 10:26:50.286 观测到两次 scancode 44 的 `keymap` 调用，处于同一毫秒。源码在一轮 SDL 队列处理完成后才发布最终 held 状态，因此瞬时按下/抬起可能在游戏采样前抵消。游戏仍在片头。
3. 10:28:09.157–09.272，Terra 对片头可见区域做一次左击；指针到达对应位置，片头继续。这不是菜单按钮或世界目标，没有建立原生点击的成功/失败结论。

窗口测试还暴露两点：隐藏启动的游戏可被捕获却不能被 sky 激活；后台捕获必须确认没有拿到遮挡窗口的内容。早期 PID 27772 后来退出，日志为正常 Exit，本轮不能将其归因为输入或探针。

sky 的 press_key 无独立 down/up 或持续时间参数；本次无法可靠构造跨游戏帧按键。应用内置脚本也未被拿来替代原生输入实验。[computer-use 技能](C:/Users/fengj/.codex/plugins/cache/openai-bundled/computer-use/26.1027.30824/skills/computer-use/SKILL.md)要求遵守其 [guidance](C:/Users/fengj/.codex/plugins/cache/openai-bundled/computer-use/26.1027.30824/docs/guidance.md)："Use only the Computer Use JS APIs for Windows app automation"。因此主菜单和城镇仍未验收，不能把本轮截图说成原生键鼠已可用。

## 4. 工具选择与效率判断

| 工具/方法 | 本项目用途 | 评估和使用方式 |
| --- | --- | --- |
| Serena | C 运行时的符号概要、CPU/线程/桥的调用关系 | 先启动服务并激活项目；`reference/ScarletNX-src` 须独立激活。主项目 ignored 结果不能作否定证据。无符号游戏二进制不靠它反编译 |
| LLVM nm / objdump | 宿主 exe 的符号 RVA、x64 桥边界 | 本轮已核对 g_mem/g_disp/g_code_lo、keymap 等。每次构建按指纹重新生成 RVA，避免各脚本散落常量 |
| Frida 17.25.0 | 当前 guest 状态、dispatch 到宿主的映射、按对象/线程的限量观测 | 主动态工具。先验证 CPU.mem 和 ABI，再采样；保存错误与阶段标记。高频过滤可用 CModule，避免每次 send/backtrace |
| Capstone 5.0.9 + pyelftools 0.33 | 批量候选 xref、定点反汇编、ELF/运行时核验 | 本轮已实测。整段扫描一次约 50 秒，应批量目标并缓存索引；零命中必须附覆盖范围。结果仍需控制流和运行时验证 |
| Ghidra | 已核验 AArch64 ELF 的定向反编译、vtable/消息结构和间接调用关系 | 下一步主静态工具；本轮未重新跑反编译。无需重做不匹配 ELF。先分析由实际对象/调用样本锚定的少数函数，不再先全量等待 |
| sky / Terra | 画面、坐标、hover/click 的视觉对照 | 必须先检查当前场景与输入消费；瞬时按键不适合作为游戏 held 状态的可靠刺激，不能以 API 成功证明游戏响应 |

Ghidra 支持指定架构导入二进制、脚本和 headless 工作流，参见[官方导入说明](https://ghidra.re/ghidra_docs/GhidraClass/Beginner/Introduction_to_Ghidra_Student_Guide.html)和[官方 headless 文档](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/RuntimeScripts/support/analyzeHeadlessREADME.md)。现有脚本可承接，不需要先引入新 RE 平台或购买工具。

## 5. 下一轮按什么顺序做

1. 先启动/连接 Serena、激活正确源码项目，核对二进制指纹及统一地址换算。
2. 使用可信 `CPU*` 解码与正对照，恢复真实控件构造、事件消费者和线程采样。旧错误 ABI 探针不继续产出否定结论。
3. 用已经验证的 fixed ELF，在 Ghidra 给 CPU/guest 对象、vtable 和消息负载建类型；从指定对象实际使用的方法反查原生鼠标入口。`0x83baa90` 当前只是有效观测锚点，不是已确认注入入口。
4. 解决可保持跨帧且合规的实验输入条件，稳定停留到主菜单，再做无输入、鼠标、原生消息的分离对照。不要反复补瞬时键或根据动画过渡猜事件命中。
5. 世界点击入口和键盘动作层尽早单独调查；必须提供坐标/目标动作语义，不转换 Npad。探针开始产生业务效果前补足 UI 线程绑定、队列/栈串行化与真实完成判据。

## 6. 本轮文件与证据

- 新工具：`tools/d3-re/assess_runtime.py`，只 attach 已运行 PID，不启动游戏、不发界面输入、不调用业务函数；临时拦截在 detach 时解除。默认 RVA 仅适用于本文指纹。
- 修复：`tools/d3-re/xref_runtime.py`；使用 `--json` 保存覆盖率、耗时和候选引用。
- 规则：根目录 `AGENTS.md`，已写入任务开始前激活 Serena、符号优先、Terra 界面委派和原生键鼠范围。
- 证据目录：`out/windows/kbm/assessment-20261101/`（被 git 忽略，本机保留；报告内关键数值已纳入版本控制）。
- 核心证据：`baseline-comparison.json`、`title-baseline.json` 及段 dump、`linear-disassembly-coverage.json`、`xrefs-fixed.json`、`live-cpu-threads.json`、`live-object-filter.json`、`title-space-hooks.json`、`ui-observation.md` 与 `ui-*.png`。

本报告不估算原生功能完成百分比或保证交付日期；现有证据足以修正 RE 方法，尚不足以确认 D3 的完整原生键鼠路径可用。
