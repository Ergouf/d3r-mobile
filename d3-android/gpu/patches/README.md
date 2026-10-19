# GPU 依赖交接

`dependencies-20261019.json` 保存成功构建所用目录、origin、commit 和本地修改。
这些目录被 .gitignore 排除，单独克隆主仓库不能直接构建。

Eden 基线 `e0d47f2790e3f758fa2188926a0bb2f56af6b310`，保留所需 externals/submodules。
`eden-local-20261019.patch` 保存此前 `common/thread.h` 和 `video_core/cdma_pusher.cpp`
两处 Android libc++ condition-variable/stop-token 适配。本次没有重新修改 Eden。
停止条件仍依赖等待被唤醒后检查，完整 shutdown 行为未全面验证。

现有机器已应用；本次 reverse apply check 通过。新环境检出相同基线后，在仓库根运行：

```powershell
git -C reference/eden apply --check ../../d3-android/gpu/patches/eden-local-20261019.patch
git -C reference/eden apply ../../d3-android/gpu/patches/eden-local-20261019.patch
```

其余依赖按清单恢复到对应 commit；libadrenotools 构建器校验固定 revision。
`adrenotools-mali-isolation.patch` 修复 Mali 与已预载系统驱动同名时的复用：
在非共享 namespace 中先用绝对路径及 FORCE_LOAD 加载补全核心，再加载 wrapper，
系统/vendor 依赖继续链接，不修改系统分区。仅对 `vulkan.mali.so` 路径启用。
`tools/build_adreno.py` 自动检查并幂等应用；恢复依赖不再只需原始 revision。
`tools/probe_driver.cpp` 的 `--system-first` 场景在 X200 Pro 上能同时映射两套库，
并枚举 Mali-G925；app 内仍需分别核对 maps 和实际渲染日志。
Boost 是本地 archive，路径 `d3-android/gpu/third_party/boost/boost_1_86_0/`，
需另行保留或恢复 1.86.0。恢复依赖后运行：

```powershell
python -I d3-android/gpu/tools/gen_shaders.py
```

然后构建 GPU。PS1 当前包含 `D:\workspace\Diablo` 和 SDK/NDK 的硬编码路径，迁移时调整。
