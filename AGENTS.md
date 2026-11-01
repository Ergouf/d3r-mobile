# 仓库协作约定

## 开始任务前

- 每次开始任务，先确认 Serena MCP 服务可连接；服务未运行时先启动，再激活当前项目。完成后才进行代码探索或修改，不要等到需要查符号时才启动。
- 本机服务入口为 `http://127.0.0.1:9144/mcp`，可用 `d3-android/tools/serena_query.py` 连接。已有服务可用时直接复用，不重复启动。
- 本机启动命令：`serena start-mcp-server --project "D:/workspace/Diablo(fegnjl)" --transport streamable-http --host 127.0.0.1 --port 9144 --enable-web-dashboard false --enable-gui-log-window false --open-web-dashboard false`。后台启动使用隐藏窗口，日志放入 `out/`。
- 服务就绪后调用 `initial_instructions`（同一会话只读一次），并用 `get_current_config` 或符号查询确认项目已激活、符号服务可用。首次连接已有服务时显式激活当前项目，避免沿用其他仓库的上下文。
- 分析 `reference/ScarletNX-src` 时，将该目录单独激活为 Serena 项目；主仓库忽略该目录，不能把主项目下的 ignored/空结果当作没有代码或没有引用。
- 若启动或激活失败，先定位并尝试修复；仍不可用时明确说明原因，再按最小范围使用其他方式继续，不伪称已使用 Serena。

## 代码探索

代码探索优先使用 Serena 的符号概要、符号查询、引用查询。只有符号级上下文不足时，才读取完整文件。

## 电脑与浏览器界面操作

所有 computer-use（电脑界面操作、浏览器界面操作及视觉交互验证）工作均委派给 GPT-6.1 Terra（模型标识 `gpt-6.1-terra`）子代理执行，主代理不自行进行 computer-use。用户于 2026-10-28 明确指定此长期偏好（原文模型名为 GPT-6.1 Teera，按可用模型 GPT-6.1 Terra 记录）。若该模型不可用，应说明情况，不擅自改用其他模型执行 computer-use。

## D3 原生键鼠范围

只做原生键鼠：鼠标事件、游戏内世界点击/目标交互和键盘动作直接进入游戏输入或动作层。不开发键鼠转 Npad、鼠标转摇杆、虚拟手柄或“设焦点后合成 A”，也不把这些作为保底或交付替代。
