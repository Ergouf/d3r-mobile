# 当前状态与验收（索引）

更新：2026-11-11。项目按平台拆分，状态分别维护：

- Android：[android/docs/STATUS.md](../android/docs/STATUS.md)
- Windows：[windows/docs/STATUS.md](../windows/docs/STATUS.md)

构建入口：[Android](../android/docs/BUILD.md)、[Windows](../windows/docs/BUILD.md)。目录约定见 [STRUCTURE.md](STRUCTURE.md)。

两平台的实现路径、历史阶段与具体踩坑见 [逆向过程与踩坑](REVERSE-ENGINEERING.md)；实测结论仍以各平台状态和所标注的构建为准。

规划入口：[S2Arm 迁移与功耗优化路线图](../android/docs/S2ARM-MIGRATION-ROADMAP.md)，以 Android 暗黑 3 为主线，另定义 Windows 可复用范围和独立验收；当前是实施计划，未证明任一平台的新增节电收益。

## 维护口径

标题、菜单、视频、加载、静置和战斗分别记录；原生渲染/guest 提交、上屏和生成帧率分别记录。测试通过只覆盖明确列出的范围，不以构建成功或进入第一章替代完整玩法验收。过期逐轮报告不再作为当前入口。
