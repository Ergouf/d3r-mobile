# Android 构建与运行

在项目根目录运行命令。当前验收范围见 [状态](STATUS.md)，固定依赖见 [依赖说明](DEPENDENCIES.md)。

## 输入与工具链

- Android SDK Platform 36、Build-Tools 36.0.0、NDK `28.2.13676358`、OpenJDK 17、Python 3.12、PowerShell 7、Git、CMake/Ninja。
- 当前机器 SDK 为 `D:\workspace\Gdict\android_sdk`。脚本仍有本机默认路径，迁移时使用 `--sdk`、`--ndk` 参数或调整脚本路径。
- `android/gpu/build_gpu.ps1` 和 `android/gpu/probe/coverage.ps1` 当前将项目根固定为 `D:\workspace\Diablo`；本机这是指向实际仓库的 junction。迁移时须先检查该路径的目标或调整脚本，不能仅从新目录启动就假定 GPU 代码会读取新目录。
- 保留原始 `libd3guest.so`、与目标安装身份匹配的 keystore、游戏资源和存档。这些输入放在本地专用目录，不能依赖临时构建目录，也不纳入 Git。
- 已验证 guest SHA-256：`dd050ef63cbaeaaeae9f7c842b26456a05d7482aaf9b91103a9bf0e0188625a2`。

本地输入位置：

| 路径 | 内容 |
| --- | --- |
| `local/android/libd3guest.so` | 保留的原始 guest |
| `local/android/signing/validation-debug.keystore` | 现存 validation 调试签名，不能代替原 genshin 包签名 |
| `local/android/packages/validation/` | 独立验证 APK |
| `local/android/packages/installed-baseline/` | 原安装基线 APK，身份及签名与 validation 不同 |
| `local/android/drivers/driver-copy.tar` | Android 驱动相关本地材料 |
| 安装目录 romfs | 工作区副本已于 2026-10-21 清理；需要时从 `D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000_data\romfs` 复制 |
| `local/assets/android/voice-zh/` | 14 个中文 CPK |
| `local/saves/android/` | `before-test.tar` 与 `after-baseline.tar` 两份 Android 存档备份 |

原始 XCI、提取 ExeFS、密钥分别集中在 `local/assets/game/`、`local/assets/exefs/`、`local/assets/exefs_update/` 和 `local/keys/`；固件、厂商驱动放 `local/firmware/`、`local/drivers/`。它们不进入源码 Git。

## 依赖与着色器

按 [固定依赖清单](../../android/gpu/patches/dependencies-20261019.json) 恢复 `android/third_party/eden` 与 `android/gpu/third_party/`。克隆本仓库不会自动取得这些目录。保留 Boost 1.86.0 本地 archive，以及清单要求的子模块。

Eden 基线检出后应用 [本地适配补丁](../../android/gpu/patches/eden-local-20261019.patch)。已有补丁的工作树不要重复应用；先检查状态。libadrenotools 的 Mali 隔离补丁由构建器校验并幂等应用，详见 [GPU 补丁说明](../../android/gpu/patches/README.md)。

```powershell
python -I android/gpu/tools/gen_shaders.py
```

生成器使用 NDK shader-tools 的 `glslc.exe`，输出到 `out/android/generated/include/`。GPU 构建和 coverage 检查会自动调用 `--ensure`，补齐缺失或过期头文件；不需要恢复旧 `android/gpu/gen/`。脚本中的工具链路径须与本机安装一致。

## 构建 APK

推荐使用统一 profile 构建器，显式传入保留的 guest 和签名文件：

```powershell
python -I android/tools/build_android_profile.py --profile validation --guest local/android/libd3guest.so --keystore local/android/signing/validation-debug.keystore
```

它构建 adrenotools、GPU、host 和 APK，不安装。产物统一放在 `out/android/`：profile 包放在 `{profile}/host` 与 `{profile}/apk`，独立 host 放 `host/`，GPU 放 `gpu/`，驱动工具放 `adrenotools/`，诊断输出放 `probes/`。这些目录均为可重建产物。

当前工作树的 `GraphicsDefaults.java`、`PresentationPolicy.java`、`app/res/`、场景相关 host 源码、Eden 场景/同步补丁和部分回归测试尚未被主仓库 Git 跟踪；保留或迁移当前源码时应连同已修改文件检查 `git status --short`。仅检出已有提交不能保证重建当前候选。

可选 `--profile genshin`、`genshin-bilibili` 分别使用 `com.miHoYo.Yuanshen`、`com.miHoYo.ys.bilibili`。身份选项不等于 OEM 插帧已经工作。不要覆盖设备上的真实原神或使用不匹配签名更新既有包。

APK 现使用本机既有暗黑 3 启动图标（`D:\Games\DiabloIII\diablo3.ico`），五档 launcher PNG 位于 `android/app/res/mipmap-*/`，来源说明为 `android/app/ICON-SOURCE.txt`；未生成或重新设计图案。打包器先用 aapt2 编译资源，再链接 Manifest。

### 场景分层与画质实验

画面设置现将场景线性放大与实验 FSR 分开标示。场景偏好值 `625/75/80/875` 分别对应 0.625×、0.75×、0.8×、0.875×，UI/文字保持 `2000×900`。`10` 为原生 1×；新候选首次启动将旧偏好统一迁移到 1×，之后保留用户手动选择。这些缩放选项不代表已找到推荐配置。选用场景缩放时默认使用传输线性放大；私有 `profile-scene-fsr` marker 保留 EASU + RCAS 实验入口。用户已确认修正版仍是“UI 正常，场景全黑”，FSR 世界画面验收失败；原生 1× 城镇的场景与文字已获用户确认正常。

诊断时在目标包私有 `files/runtime/` 创建 `profile-scene` 后冷启动，生成 `scene-draws.jsonl`，包括 shader 指纹、真实 framebuffer 范围、纹理/深度缩放状态、常量缓冲 crop 和成功执行的 FSR 记录。移除 marker 并重启即可关闭。记录是诊断数据，不能用于性能对比。原尺寸基线与测试模式均需分别在城镇和物品栏采集；编译成功不能替代 UI、深度/模板、方向、裁剪、性能或功耗验收。

2026-11-10 复核发现两个 Vulkan 用法错误并已修正：FSR 的 EASU/RCAS 中间图用于 blit 源时缺少 `TRANSFER_SRC` usage（VUID `vkCmdBlitImage-srcImage-00219`、`VkImageMemoryBarrier-oldLayout-01212`）；线性分支把逻辑 `1600×720` 当作物理 `1200×540` 源图范围，且未应用 crop。现在中间图显式声明传输源用途，线性 blit 按物理像素与 crop 取图。`scene-draws-ingame.jsonl` 已有 `09346d588c3f3203` compositor、`uv` 和 `source_size`；draw 日志会去重，不能根据后续行缺少这些字段推断未识别 compositor。另已移除场景补丁中重复的 syncpoint 改动，干净基线按构建顺序重放及逐文件比对通过。

2026-11-10 的 validation 候选 APK SHA-256 为 `7439ED1A6323A666B9AB4DE86B393B8E963FFB7C9F6C3DF677C86A0DBE7AA500`，运行库为 `F7DC1B49A019393A6324301BD755FCE74796D33F011B46C72F244AD279469D1F`。当时使用自定义 Mali 驱动，并按用户要求从 Windows 当前安装导入 70 级英雄存档；稳定快照与清单在 `local/android/imports/windows-20261110-153338/`。2026-11-11 在设备旧包已不存在后重装相同 APK、恢复并核对四个存档文件，当前短时启动使用系统 Vulkan，未恢复旧自定义驱动配置。早前 `4C1FA41A…` 的 `60.13/60.15` 短窗没有证明世界画面恢复或长时锁帧。回退包分别保存在 `out/android/fsr-contract/rollback-7439ed1a.apk` 与 `rollback-4c1fa41a.apk`，覆盖安装须保留原签名和应用数据。

`7439ED1A…` 增加了可在线切换的 `profile-scene-fsr-fp32` 和 `profile-scene-fsr-easu` 标记；与 `profile-scene-fsr` 配合，在 GPU 线程每 32 次接受的合成中检查一次。`profile-scene-passthrough` 优先回到线性传输。另在 `profile-scene` 下启用 `profile-scene-pixels`，可将输入、EASU、RCAS、合成目标的 16×9 点像素统计写入 `scene-pixels.jsonl`（前 8 次，随后每 600 次）。像素采集强制 GPU 完成并回读，只用于定位全黑阶段，不参与功耗/帧率比较。这些诊断已构建，尚未在世界场景执行 FP32/像素对照。

宿主现实现 30/36/40/45/60 FPS 软件上限，无追赶式突发。新版本首次启动迁移为 45 FPS 上限及系统控制的刷新率，并移除旧的私有 `profile-frame-cap` 诊断覆盖。默认不设置窗口刷新率/模式，也不调用 Surface 帧率提示；仅在用户显式选择刷新率时请求对应模式。后续可在设置中修改，帧率上限的修改不再自动改变刷新率；重新创建该文件仍可用于诊断覆盖。设置变化须冷启动。不能把离线期限测试或短窗均值当作稳定上屏帧率。

2026-11-11 的已安装包为 `out/android/45fps-vsr/apk/d3host-recovery-debug.apk`（SHA-256 `B397B77317D473191A617167948BC418D36E50F2A53BE2D54C7ADBC615C8812E`），身份 `com.miHoYo.Yuanshen`。为避免引入额外原生变更，该包显式复用手机安装前 `7A2A6999…` 包所含宿主库 `ABB41E19…`；guest、驱动 hook、资源和 Manifest 也与该包一致，ZIP 条目仅 Java 字节码和签名文件有变化，手柄相关字节码核对一致。完整源码另已构建成功，但生成的原生库不是此安装包所使用的版本。签名证书与旧包一致，ZIP 完整性和 16KB 对齐检查通过；设备 APK 与宿主库哈希一致。用户操作后的采样未达到持续稳定 45 FPS，也未证明 VSR 的最终生成输出，窗口与边界见 [状态](STATUS.md)。

历史 genshin APK 位于 `out/android/genshin/apk/d3host-recovery-debug.apk`，当时设备拉取副本 SHA-256 为 `53D8E825D6E3E48EE31F210A01D68A7CBE409338699718281EC6D0E9E64DE99C`。先前 validation 存档、配置和驱动备份在 `local/android/backups/validation-20261110-105524/data.tar`。用户随后卸载过 validation，本轮已重装和导入存档；历史安装状态不作为当前安装身份。

GPU 增量构建现使用 Clang `-MMD` 依赖文件，检查 Eden 与 host 头文件时间；缺少依赖文件时重编，避免模板头修改未进入 APK。

分步构建：

```powershell
python -I android/tools/build_adreno.py --sdk <sdk> --ndk <ndk>
pwsh -File android/gpu/build_gpu.ps1
python -I android/tools/build_host.py --with-gpu --ndk <ndk> --output-dir out/android/host
python -I android/tools/build_apk.py --host out/android/host/libd3host.so --guest local/android/libd3guest.so --keystore <匹配目标身份的keystore> --output-dir out/android/recovery/apk
```

## 内容与存档

APK 不包含主游戏或约 5.2GiB 中文 DLC。主资源默认位于设备 `/data/local/tmp/d3romfs`；资源检查工具见 [resource_recovery](../../android/tools/resource_recovery/README.md)。

中文 title ID 为 `01001b300b9bf00b`，DLC index 为 `11`。完整部署位置为 `/data/local/tmp/d3romfs/AddOnContent/11/`，14 个 `ztCN_*.cpk` 总计 5,609,750,528 bytes。逐文件校验后写 `.d3-content-complete`，内容为 title ID 加换行；不完整安装不得写完成标记。主资源须使用匹配更新版本的 CoreCommon/ServerCommon。

另有 DLC index `100`、`101`、`102`，对应 title ID `01001b300b9bf064`、`01001b300b9bf065`、`01001b300b9bf066`。2026-11-11 从保留 XCI 提取的 NCA 和文件存于 `local/assets/android/s2arm-dlc/`；设备对应目录各含一个 `.data` 文件和校验后写入的完成标记。三份文件的大小与 SHA-256 均匹配 `out/android/s2arm/artifact.json`；validation 应用身份下的生产内容枚举探针可找到 `11, 100, 101, 102` 并打开新增文件，真实游戏启动日志也显示全部四项被枚举和挂载。游戏内奖励效果尚未验证。

留存 S2Arm 包的 789 项资源已按 `out/android/s2arm/artifact.json` 恢复到 `local/assets/android/s2arm-restoration/resources/`，逐项校验 SHA-256；直接图形描述符的工具校验通过（无离线 program 文件）。其导入回执与 APK 哈希、内容根和 artifact 哈希匹配，安装流程日志保存在 `out/android/s2arm/m0-native-tests/s2arm-import.log`。设备原有大资源按哈希校验后在本机复制进暂存目录，其余文件由 ADB 推送；经应用安装事务完整验证后，暂存副本已删除。该资源绑定证明不等于可复现构建或正确出图。

应用存档位于相应包的 `files/runtime/saves/`。备份整个存档目录；复用原签名执行更新，保留应用数据。不同 profile 的私有路径和存档互相独立。

Windows 当前安装的存档源为 `D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000_data\save\user.0123456789abcdeffedcba9876543210\`。Android 本地账户目录为 `files/runtime/saves/1-0000000000000000-4433484f53545531-4c4f43414c555345-0000000000000000-00000001/`。导入时保留 `account.dat`、`profile.dat`、`prefs.dat` 与 `heroes/*.dat` 的目录关系，复制前后核对源文件稳定，逐文件核对设备 SHA-256；存档副本和唯一材料保存在 `local/`。

## 回归与实机检查

```powershell
python -I -m unittest discover -s android/tests -p 'test_*.py' -v
bash android/build.sh --build-tests
```

Java 测试在 `android/tests/java/`。native 测试构建成功不等于已经在 ARM64 设备执行；指定目标设备串行运行并记录退出码。正常基线使用系统 Vulkan、1.0×、write-watch 关闭。

### 帧时和电量采集

`tools/capture_android_runtime.py` 只读采集指定包，核对安装 APK 哈希、PID、进程启动 ticks 和 boot ID；它不会启动游戏或确认当前场景。采集前先确认实际游戏场景，不能把开场视频或菜单帧率当作实战结果。`--output-dir` 必须是新目录。

采样窗口使用设备 `CLOCK_MONOTONIC`；`/proc/uptime` 包含 suspend 时间，不能拿来直接过滤 logcat。先使用 NDK 将 `tools/android_clock.c` 编译为 ARM64 可执行文件，部署到 `/data/local/tmp/android-clock` 并设为可执行。该工具只读取 monotonic、boottime 和 realtime 三种时钟，不修改设备设置。未提供时钟 helper 的采集会保留原始数据，但严格汇总拒绝伪造采样窗口。

电池 sysfs 不可读时可为 `capture_android_runtime.py` 增加 `--battery-current`，通过 `service call batteryproperties 1 i32 2` 查询 Android `CURRENT_NOW`，记录带状态的 `current_now_ua`；不支持、权限错误和异常 Parcel 保留为不可用。X200 Pro 已与应用 `BatteryManager.getIntProperty(2)` 交叉核对可读，15 秒实采取得 8 个有效读数 `-139000…-79000 µA`。汇总的 `battery_net_current_ua` 仅表示电池净电流（负数放电）；USB 连接时仍不计算平均放电量或整机功耗，不能据此宣称省电。证据：`out/android/fsr-contract/power-service-capture/`。

拔线采样使用 `capture_android_battery.sh` 在设备本地运行，由 `collect_android_battery.py` 校验身份、时钟、原始分块并汇总。脚本有温度阈值、停止标记和退出清理；正常结束、身份变化、错误均须关闭游戏，编译/分析/等待期间保持关闭。启动前跳过片头 CG，窗口前确认实际场景，下一轮须等温度回落。无线 ADB 中断不等于游戏崩溃；用退出历史区分系统清理和 native fault。

`7439ED1A…` 的一次拔线候选窗口（请求场景 0.75× 线性、上限 60）实测：118.45 秒/57 点，所有外部供电为 false，Android 电池电压乘净放电电流的梯形积分均值 **6.674 W**，温度 33.1–33.4°C；电流积分 51300 µAh，与计数器减少 49000 µAh 的比值为 0.955。原生 composite 均值 **45.94 FPS**，帧间隔 P50/P95/P99 为 20.825/24.063/25.214 ms。这是该候选及诊断配置的整机电池侧窗口，实际场景与上屏还需复核，不能泛化为战斗结果。既未锁 60，也未达到用户现要求的 **≤4.5 W**（3.8 W 为更早目标）。同窗完整扫描批次平均每轮 37281 页、87 页变化、10.579 ms。证据：`out/android/fsr-contract/battery-75-linear-60-01/analysis-summary.json`。另一个 0.625×/30 候选因身份变化提前结束，退出历史记录为 cleaner 请求 force-stop，未形成有效功耗结果。

```powershell
python android/tools/capture_android_runtime.py --serial <序列号> --package com.d3mobile.host.validation --duration-s 120 --interval-s 2 --cpu-ticks --clock-helper /data/local/tmp/android-clock --output-dir out/android/performance/town-baseline
python android/tools/summarize_android_runtime.py --logcat out/android/performance/town-baseline/logcat.txt --samples out/android/performance/town-baseline/samples.jsonl --manifest out/android/performance/town-baseline/manifest.json --output out/android/performance/town-baseline/summary.json
```

汇总必须传入对应 manifest，以设备 monotonic 窗口排除同 PID 的历史日志。采集器在采样期间持续读取 logcat，避免仅在结束时转储导致环形缓冲覆盖。原始日志和逐条命令审计保留在采集目录。存在外部供电时，放电均值为 null；不能用 USB 充电采样宣称省电。电量计数需要在真实拔线放电时另行验证其更新和单位。

需要逐帧诊断时，在该 profile 私有 `files/runtime/` 下创建 `profile-frame-timings` 文件，再重启应用进程；移除文件后重启即可关闭。诊断默认关闭，正式功耗比较应关闭逐帧日志。`frame_interval_us` 是连续成功 composite 的间隔，`total_us` 仅是宿主 present 回调的墙钟用时；`gpu_wait_us` 还含 worker、驱动和呈现等待，不能当作 GPU 时间戳。`present_us` 包含 `gpu_wait_us`，不可相加。`cpu_us` 只计该回调线程。以上指标均不能替代实际场景与上屏验证。

开启诊断时还会写入私有 `files/runtime/frame-timings-<PID>.log`，作为普通 Android 日志不可用时的补充。该文件使用相同 monotonic 时间格式；在核对当前 PID 与安装身份后，可用 `adb exec-out run-as <包名> cat <相对路径>` 拉取，并作为汇总器的 `--logcat` 输入，仍必须传对应采集 manifest。它是可清理诊断产物，不是游戏存档。

诊断模式内可用 `files/runtime/profile-poll-fences` 临时恢复原 1ms fence 轮询作为同进程 A/B 对照；移除该文件回到事件等待。开关每 32 帧检查一次，日志记录 `poll_fences`，切换后等待生效再开始新采样窗口。非诊断运行始终使用带超时的事件等待，不读取此开关。该对照只改变 fence 等待，不改变清晰度、存档或图形工作负载。

`cache-scan` 的单点 `us` 每 256 轮记录一次，恰好与 write-watch 的全量审计周期重合，不能用来推算开启跟踪后的常态成本。新的 `batch_count/batch_total_us/batch_max_us` 覆盖该日志之前的全部扫描；以总用时除以次数计算均值，最大值不能当作分位数。`batch_begin_us` 为该批次首次扫描的 `CLOCK_MONOTONIC` 微秒时间，分析时只纳入起止均落在采集窗口内的整批，避免混入窗口之前的工作。`batch_pages/batch_changed` 为批次内页面数量之和，不是驻留页数。

受控 write-watch 实验可在启动前同时创建 `gpu-write-watch` 和 `profile-full-cache-scan`，在保留信号路径的情况下先使用全量扫描进城。进入同一场景后移除/创建 `profile-full-cache-scan`，即可在同进程比较跟踪与全扫描，每 32 个扫描轮次检查一次；强制全扫描会先恢复已跟踪页面的写权限，并保留处理未决 fault 所需的元数据。切换后等待至少 4 秒，核对逐帧 `cache_mode`：`0` 为未启用 watch、`1` 为 watch、`2` 为 watch 进程内强制全扫描。跨模式的未完整扫描批次会丢弃。此控制只在逐帧诊断开启且进程启动时已启用 watch 的情况下生效；正常配置仍关闭 write-watch。

`rebuild_and_probe.ps1` 默认使用隔离的 validation 身份，以及保留的 validation 签名；可显式传入 `-Profile`、`-Package`、`-Guest`、`-Keystore`、`-Python`。它检查输入后才构建，安装只使用 `adb install -r`，probe 传入 `-Keep` 保留应用数据。默认签名不能用于覆盖原 genshin 身份。

`gpu-write-watch` 是未完成实机验收的实验开关，不能作为默认优化。安装前确认设备序列号、包名和签名，避免卸载、清数据或混用 profile 存档。

离线缓存候选将 `CpuWriteTracker` 的每页 4120 字节混排项改为 24 字节元数据与连续快照两组数组。干净 watch 遍历不再逐页跨越快照；精确 `memcmp/memcpy`、连续快照、256 轮全量审计和交换删除语义保留。仅在最近比较页数、新缓存页或审计需要时唤醒两个工作线程。GPU 库 355/355、宿主链接及 ARM64 tracker/布防测试程序编译通过；2026-11-11 用当前源码重新编译后在手机串行执行 tracker、布防、内存区域、stack、HID 和 guest TLS 测试，均退出 0，证据在 `out/android/s2arm/m0-native-tests/device-results.json`。**候选 APK 尚未安装，也未证明帧率或节电改善**。候选 APK 为 `out/android/fsr-contract/cache-layout/apk/d3host-recovery-debug.apk`，SHA-256 `ABE30F018960FB1C87F04162067D2465943B4D63967B79D9D5A3BA1C1FCE1DF9`；签名与 `7439ED1A…` 一致，ZIP 项目完整，含四个 driver hook，payload 只有 `libd3host.so` 改变。旧头文件与 `7439ED1A…` 回退包均已保留。
