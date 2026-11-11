# GPU 固定依赖与补丁

`dependencies-20261019.json` 保存成功构建所用目录、origin、commit 和本地修改。
这些目录被 .gitignore 排除，单独克隆主仓库不能直接构建。当前步骤见 [Android 构建说明](../../../android/docs/BUILD.md)，依赖许可见 [依赖说明](../../../android/docs/DEPENDENCIES.md)。

Eden 基线 `e0d47f2790e3f758fa2188926a0bb2f56af6b310`，保留所需 externals/submodules。
`eden-local-20261019.patch` 保存此前 `common/thread.h` 和 `video_core/cdma_pusher.cpp`
两处 Android libc++ condition-variable/stop-token 适配。
停止条件仍依赖等待被唤醒后检查，完整 shutdown 行为未全面验证。

`eden-syncpoint-wait.patch` 增加有绝对超时的 host syncpoint 事件等待，保留计数器回绕比较；Android host 用它替代 present fence 的 1ms 轮询。`build_gpu.ps1` 在构建前校验并幂等应用此补丁，不替代前述基线适配补丁。对应 ARM64 实机单元测试源码为 `android/tests/test_syncpoint_wait.cpp`；性能收益必须另做同场景比较。

`eden-scene-fsr.patch` 接入 Android 场景分层（`D3_ANDROID_SCENE_FSR`）：匹配场景 shader 后按设置缩放场景附件，UI 附件保持 1×；当前可选比例见 [Android 构建说明](../../docs/BUILD.md)。host 在 `gpu/host/scene_fsr.*` 中用 `vkCmdBlitImage` 将场景线性回写，绕开 vivo GameLib VSR 的 render pass/描述符崩溃点；私有 `profile-scene-fsr` marker 保留 EASU + RCAS 实验入口，但此前 Mali-G925 世界画面实测全黑。纯裁剪/视口校验在 `scene_region.h`，对应测试为 `tests/test_scene_region.cpp`。2026-11-10 X200 Pro 已实测 `1200×540 → 2000×900`，主菜单和城镇 HUD 正常，最终精确构建连续 `draw=2100` 无崩溃；同一回写路径的清理前构建另已进入城镇并跑到 `draw=7200`。画质、战斗性能与功耗仍待量化。

2026-11-10 代码复核已为 FSR 中间图补齐 blit 所需 `TRANSFER_SRC` usage，并修正 host 线性路径的物理源范围和 crop。场景补丁已去掉与 `eden-syncpoint-wait.patch` 重复的段落；干净基线依次应用两补丁、对照当前源码及反向检查均通过。裁剪测试与 GPU 库构建通过，候选 validation 已安装；这些结果不替代 FSR 世界画面的实机验收，当前状态见 [Android 构建说明](../../../android/docs/BUILD.md)。

现有源码树已应用对应补丁。新环境检出相同基线后，在仓库根运行：

```powershell
git -C android/third_party/eden apply --check --ignore-whitespace ../../gpu/patches/eden-local-20261019.patch
git -C android/third_party/eden apply --ignore-whitespace ../../gpu/patches/eden-local-20261019.patch
```

`git -C` 会改变相对补丁路径的起点；上面的路径从 Eden 目录解析。在已有 Windows 工作树先用 `apply --reverse --check --ignore-whitespace` 判断是否已应用，不要重复应用。`build_gpu.ps1` 再按顺序幂等处理 syncpoint 和场景补丁。

其余依赖按清单恢复到对应 commit；libadrenotools 构建器校验固定 revision。
`adrenotools-mali-isolation.patch` 修复 Mali 与已预载系统驱动同名时的复用：
在非共享 namespace 中先用绝对路径及 FORCE_LOAD 加载补全核心，再加载 wrapper，
系统/vendor 依赖继续链接，不修改系统分区。仅对 `vulkan.mali.so` 路径启用。
`tools/build_adreno.py` 自动检查并幂等应用；恢复依赖不再只需原始 revision。
`tools/probe_driver.cpp` 的 `--system-first` 场景在 X200 Pro 上能同时映射两套库，
并枚举 Mali-G925；app 内仍需分别核对 maps 和实际渲染日志。
Boost 是本地 archive，路径 `android/gpu/third_party/boost/boost_1_86_0/`，
需另行保留或恢复 1.86.0。恢复依赖后运行：

```powershell
python -I android/gpu/tools/gen_shaders.py
pwsh -File android/gpu/build_gpu.ps1
```

着色器生成头写入 `out/android/generated/include/`，GPU 对象和静态库写入 `out/android/gpu/`，libadrenotools 写入 `out/android/adrenotools/`，coverage 结果写入 `out/android/probes/`。GPU 构建与 coverage 会自动调用生成器的 `--ensure`，复用最新头文件并补齐缺失或过期文件。

`dependencies-20261019.json` 和补丁文件名中的日期是固定版本标识，不是待清理的测试报告。PS1 仍包含本机项目与 SDK/NDK 的默认路径，迁移机器时调整；不要把可重建输出放回 `android/build/` 或 `gpu/gen/`。
