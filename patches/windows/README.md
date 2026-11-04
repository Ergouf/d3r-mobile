# ScarletNX Windows 补丁

`reference/ScarletNX-src/` 是本地上游检出，不纳入主仓库。本目录保存 Windows FSR 与原生键鼠运行时的可重放源码差异。

- 上游：<https://github.com/scarletnx/ScarletNX>
- 基线提交：`dbf8915965367e8a9616b19e5a0c1eddafaf28f3`
- 有效链：`0001–0028`、`0031–0034`
- `0029`、`0030` 是已放弃的实验，不进入当前链，也不能按目录全量应用
- 每一步的补丁 SHA-256 和结果文件 LF 规范化 SHA-256 都记录在 `base.json`

## 应用与验证

```powershell
git clone https://github.com/scarletnx/ScarletNX.git reference/ScarletNX-src
git -C reference/ScarletNX-src checkout dbf8915965367e8a9616b19e5a0c1eddafaf28f3
.\patches\windows\Apply-Patches.ps1 -CheckOnly
.\patches\windows\Apply-Patches.ps1
python .\tools\windows-dev\verify_patch_chain.py
```

已有检出时不要重新 clone 或覆盖源码。应用脚本核对基线、顺序和哈希；已完整应用时直接返回，不重置工作树。`verify_patch_chain.py` 在临时 worktree 重放 `base.json`，原工作树不会被修改。

Windows 仓库路径含括号时，构建使用无括号 junction（例如 `D:\workspace\Diablo-kbm`），避免 cmd/CMake 参数截断。构建说明见 [Windows 工具说明](../../tools/windows-dev/README.md)，当前验收与已知缺口见 [当前交接](../../docs/windows/HANDOFF-20261104-CURRENT.md)。

## 补丁分组

- `0001`：FSR1 EASU/RCAS、Vulkan 图像布局与资源寿命、全屏启动，以及默认关闭的呈现统计。
- `0002`：可配置的鼠标/触摸/摇杆兼容行为。
- `0003`：游戏线程 guest 调用桥、输入队列和触摸门控。
- `0004–0008`：HID 鼠标、原生动作键、鼠标按键及按下/释放生命周期。
- `0009–0018`：世界指针、目标拾取、走近、Operate/Attack、轮盘与键位信息。
- `0019–0025`：主菜单、角色页签、装备格、技能类别等 UI 鼠标路径。
- `0026–0027`：PC 光标和双按钮提示框。
- `0028`、`0031–0033`：waypoint/门的 walk-into、投影候选和遮挡门控。
- `0034`：`Tab` 仅在世界界面打开地图；其他游戏 UI 打开时不下发菜单 Down 动作。

## 已知边界

- `0027` 目前只覆盖观察到的固定双按钮形状，发送全局 A/B，尚无最上层与焦点一致性门控。
- 商人/工匠顶部页签是 `0x90ABB48` 视图按钮但 `+0x118` 无 callback；尚未完成精确鼠标切换。
- 门补丁只对已测入口形成业务结论；`90419`、蓝 portal 和地牢仍未完成。
- 构建成功、补丁重放通过和 `operate accepted` 都不等于交互业务通过。

上游代码为 GPL-3.0-or-later；AMD FSR 算法许可保留在 [AMD-FSR1-LICENSE.txt](../../licenses/AMD-FSR1-LICENSE.txt)。
