# Windows 当前状态与验收

更新：2026-11-11。本文件只记录 Windows 路径的已验收范围与剩余工作；构建见 [BUILD.md](BUILD.md)，发行见 [RELEASE.md](RELEASE.md)，Android 见 [Android 状态](../../android/docs/STATUS.md)。

> **当前 Windows 安装为 0145（2026-11-10）**：运行时 SHA-256 `64EED1B0E0CDF55C970E729CE2DE159F826E1D477F932E357B9C547F1F5B5821`。场景 0.75× → 内置 FSR → 原尺寸 UI/文字的显式实验已在城镇和物品栏核对；普通启动保留既有配置。相关 6 项 CTest、深度/模板 GPU 回读与补丁链重放通过，验证日志 0 VUID/SYNC 错误（有 10 条原生深度绘制 unused-color-output 警告）。这些结果不证明省电、实际插帧或全部 KBM 行为已在 0145 重验；功能验收沿用各条注明的构建。详见 [当前交接](HANDOFF-20261104-CURRENT.md)。

2026-11-11 只读核对安装 exe 哈希仍为上述值，安装 INI 为 `resolution=1.75`、`upscaler=1`、`shadows=1`；后台启动器也默认传入 1.75×。原发行包默认值是 1×。同日本机补丁链 132 阶段重放通过；末项 `0146` 仅修正测试，不改变安装运行时。`0145-scene-fsr-before-ui.patch` 和 `0146-settings-option-tests.patch` 尚未被主仓库 Git 跟踪，需与 `base.json` 一并纳入版本管理才能从提交重建完整链。

Windows 路径基于 ScarletNX 固定提交 `dbf8915965367e8a9616b19e5a0c1eddafaf28f3`，与 Android 兼容层是独立构建。

**S2Arm 复用规划（2026-11-11）**：NVN→Vulkan、资源变化跟踪、批处理和 shader 缓存列为可复用候选；ADPF 属于 Android 接口，VRS 及设备缓存须按 Windows 显卡另行适配。[路线图第 10 节](../../android/docs/S2ARM-MIGRATION-ROADMAP.md#10-windows-可复用部分与独立路线) 定义独立接入、KBM 回归和能效验收。本轮仅补充规划，未修改 Windows 运行时、未实测节电，不继承 Android 的功耗结论或 4.5 W 门槛。

- 早期 FSR 测试在 Core Ultra 5 125H / Intel Arc 核显、驱动 `32.0.101.6078`、设备 Vulkan `1.3.293` 上运行；后续驱动升级到 `32.0.101.9150` 的验证记录见下文。
- 早期发行基线内部 `resolution=1`，游戏颜色源约 1600×900；阴影开启。FSR1 EASU + RCAS 替换最终双线性放大，RCAS 衰减 1.5 stops。该基线不代表当前安装 INI。
- 3072×1920 全屏中保持纵横比，FSR 输出 3072×1728；两次启动及全屏/窗口切换的 Khronos 验证层检查通过。
- 10 项相关设置/运行时测试、三份 FSR 着色器 SPIR-V 验证通过。描述符录制、回退图像布局、资源寿命与翻转修复已进入本地版本。
- 简体中文与中文语音 DLC 已包含；Windows 中文语音尚未完成人工听验。Xbox A 确认、B 取消，X→X、Y→Y。
- 当前安装入口为 `D:\Games\DiabloIII\暗黑破坏神 III.lnk`，直接启动运行时且没有控制台窗口；`Launch.cmd` 仍保留，发行 ZIP 解压后仍以它为入口。旧 `D:\Program Files` 安装已迁移删除；完整 ZIP 归档已在 2026-10-21 作为安装目录重复副本清理，重打包时需显式指定基线 ZIP。归档的逐文件 CRC/SHA-256、整体校验值和解压副本 25 秒启动测试记录保留在 [发行记录](RELEASE.md)。
- 2026-10-21 用当前源码重新构建并替换了安装目录运行时（SHA-256 `194e5b59…`，含 FSR1、`SNX_PRESENT_STATS`、`vk_sc_view` 与全屏前隐藏窗口），旧运行时备份在 `out/windows/backups/`，安装目录 `SHA256SUMS.txt` 已同步。同日清理工作区重复数据约 57.55 GiB：两份 Windows ZIP 归档、`local/assets/android/romfs` 与临时检查目录；romfs 的 37 个文件与安装目录逐文件 SHA-256 一致。窗口句柄 A/B 采样：旧版 0.22 秒首次可见为 1280×720 带标题栏小窗，新版 0.38 秒首次可见已是无边框 3072×1920 全屏。

此前未加本次 FSR 改动的第一章早期道路基线为约 **58.96 FPS**，来自 6,600 次 guest present / 111.94 秒；不是独立上屏帧率，也不能代表全部战斗场景。FSR 版最终实战验收尚未完成。

2026-10-21 同城镇 18 秒对照发现 120Hz 严重卡顿：60Hz 上屏帧时间 p99 为 16.69ms、最大 16.70ms；120Hz p99 为 112ms、最大 292ms。活动信号精确频率分别为 60.000485Hz 和 119.999454Hz。问题仍在诊断，尚未确认根因或修复；短窗口结果不构成长时间实战验收。

同日独立 Win32/Vulkan 清屏探针也复现：60Hz 下主机提交约 60.03fps，fence 等待最大 0.07ms；120Hz 下约 47.91fps，fence 等待最大 80.10ms。120Hz 改用 IMMEDIATE、55/65/120fps 提交目标和 720p 窗口仍有长等待；游戏旁路 FSR 也未消除卡顿。探针数据是主机调用计时，不是实际上屏帧率。现有证据将调查范围扩大到 Vulkan/Windows/驱动呈现链路，不能据此认定 GPU 清屏计算过慢或某项系统设置就是根因。IGCL 查询显示 VRR 未启用，ASP 查询返回不支持。6078 驱动已本地导出备份，Intel 9150 安装包签名验证通过，尚未安装。

重启后游戏实机（120Hz 显示器、内部 `resolution=1.5`、`anisotropy=16`、FSR1 保留）在 55 秒城镇场景共 3,301 帧：主机呈现均值 16.67ms、p99 17.83ms、最大 23.25ms；上屏间隔 p99 16.72ms、最大 16.82ms，超过 33ms 的帧为 0；GPU 时间均值 12.89ms、最大 14.38ms。即原 120Hz 严重卡顿在本次实机采样中未复现，但仍需长时间实战确认。画质侧由内部 1600x900 提升到约 2400x1350（2.25 倍像素）后再用 FSR 放大到 3072x1728，并把纹理各向异性过滤从游戏默认提升到 16x。

原生 D3D11/DXGI 清屏对照使用双缓冲 FLIP_DISCARD、最大延迟一帧，PresentMon 确认进入 Hardware Composed: Independent Flip。去除启动三秒后的 120Hz 采样中，上屏间隔 p99 约 41.65ms、最大 41.75ms；60Hz 对照 p99 约 16.86ms、最大 17.00ms。两次有效窗口分别为 20 秒和 18 秒，不作为严格等时长比值。绕开 Vulkan 的 GDI 拷贝呈现有改善，但尚未达到稳定 60fps。备用应用侧方案为 Vulkan 渲染与 DXGI 共享资源呈现，现有 FSR 可保留；尚未集成，不能宣称已修复。

实际 probe surface 的独占全屏能力查询返回支持，但两次获取独占均返回 `VK_ERROR_INITIALIZATION_FAILED`，第二次已确认窗口在前台。未渲染独占测试帧，不能将能力支持视为路径可用。当前安装目录已恢复诊断前的 FSR 运行时，INI 字节校验与原值一致，显示器恢复为 120Hz。9150 通用驱动的 INF 匹配和安装器/目录签名已核验，并已通过用户授权静默安装。2026-10-21 09:44 重启后确认 `32.0.101.9150`（2026-10-08）完整加载，状态 OK。重启后同一 Vulkan 探针在 120Hz 下为 Independent Flip、主机 60.0fps、fence 最大约 0.005ms，上屏间隔 p99 25.02ms、最大 25.06ms，无超过 33ms 的帧；60Hz 对照 p99 16.72ms。DXGI 探针 120Hz 上屏 p99 33.33ms、60Hz 16.70ms。修复前同探针 120Hz 为 47.9fps、fence 最大 80.10ms。

### Windows 待完成

1. 在非验证层模式下复测 120Hz 长期表现，并做真实战斗画质/帧时间对照，定位剩余上屏间隔问题及早期严重卡顿能否复现，确定稳定 60 FPS 时最高内部渲染档位。
2. Windows 中文对白听验和全部手柄功能、长期音画同步验收。
3. 120Hz 的帧生成集成与测量。目前只有 FSR1 空间放大/锐化，**未启用帧生成**。

构建侧测试已修正（2026-11-11）：`0008-native-action-followup.patch` 将触摸屏选项由 `Mouse too` 改为 `Fingers, mouse motion`，原来的 `runtime_settings_list` 与 `gui_settings` 仍断言旧文案。`0146-settings-option-tests.patch` 更新两处针对真实运行时设置的断言，保留单元测试中使用旧文案的独立 fixture；重新编译测试程序后，`settingsgen`、`gui_settings`、`runtime_settings_list`、`runtime_recompile_settings` 4/4 通过，完整补丁链重放通过。日志在 `out/windows/doc-audit/`。该修复没有修改运行时，也没有新增游戏实机验收。

XeSS-SR/Native AA、FSR2/3 时域方案需要运动矢量、抖动、历史数据等渲染输入；现有最终呈现图像不具备这些集成接口。当前 XeSS-FG 路径要求 DX12、XeLL 及更新驱动，不能作为这个 Vulkan 程序的现成开关。外部 LSFG 等方案尚未在本机验收。

## 维护口径

标题、菜单、视频、加载、静置和战斗分别记录；原生渲染/guest 提交、上屏和生成帧率分别记录。测试通过只覆盖明确列出的范围，不以构建成功或进入第一章替代完整玩法验收。过期逐轮报告不再作为当前入口。
