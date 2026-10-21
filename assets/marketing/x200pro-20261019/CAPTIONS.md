# X 发布素材

按 `01` 至 `04` 顺序上传 `images/` 下的四张 PNG。每张 1200×1500，4:5。
不要上传 contact sheet 代替原图。未自动替用户发布到 X。

## English

Sanctuary, in your hands.

D3R Mobile running on a vivo X200 Pro: native widescreen, floating touch controls, and Mali Vulkan bring-up. All images are real device captures.

An unofficial work in progress—not a stable-60fps or AI-frame-generation claim.

https://github.com/Ergouf/d3r-mobile

## 中文

把熟悉的世界，带到掌心。

D3R Mobile 在 vivo X200 Pro 上继续推进：原生宽屏、左侧安全区浮动摇杆，以及 Mali Vulkan 实际加载验证。配图全部来自真机截图。

非官方开发中项目，尚未完成稳定 60fps、AI 插帧或长时兼容性验收。

https://github.com/Ergouf/d3r-mobile

## 四条分开发帖

1. D3R Mobile on vivo X200 Pro. Real device capture, local Android compatibility-layer build. Requires your own game data.
2. A wider world, not a wider hero. Matching native guest resolution and aspect ratio to a 20:9 display; menu framing is adapted separately.
3. Touch inside the left movement zone. A floating origin, a following base, and neutral input on release. These real-device overlay captures use a cutscene background, not combat footage.
4. Development in the open. Mali-G925 Vulkan loading is verified from process maps and rendering logs. The completed bundle uses the device's existing core, not a newer driver.

## 表述边界

- 不宣称通关、全游戏兼容、稳定 60fps、已验证 90fps 插帧或官方移植。
- 不把标题/菜单帧率当成战斗性能，不把同代系统核心补全说成驱动升级。
- 主菜单背景边缘修复已实现候选方案；断线前未完成最终主菜单截图验收，不能写成全部修复。
- 游戏画面只做等比缩放并完整置入版面，不做 AI 生成补画或内容修饰。
- 截图属于游戏视觉内容，不属于本项目代码许可证授权的原创资产。
- 页面与素材是宣传草稿；发布前可自行调整文案，不必宣称正式发布。

## 再生成

安装 Pillow 后，在 Windows 运行 `python marketing/x200pro-20261019/render.py`。
字体取自本机 Windows；不随仓库分发。截图来源及哈希见 `sources.json`。
