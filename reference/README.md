# 本地参考源码与分析输入

- `ScarletNX-src/`：Windows 上游 Git 工作树，包含本地 FSR1 修改；可重建补丁见 `../patches/windows/`。
- `eden/`：Android GPU 固定版本源码；本地改动由 `../d3-android/gpu/patches/` 记录。
- `d3-symbols/`：当前 guest 匹配的 SDK 符号表。
- `tools/`：本地资源处理工具，构建产物和游戏输入不放在这里。
- `d2r-mobile/`：保留的早期兼容层参考源文件，不是当前编译入口。
- `legacy-recovery/`：原有源码恢复快照，保留原字节及来源说明，不参加正式构建。

游戏资源、guest、签名和存档统一在 `../local/`；生成结果统一在 `../out/`。平台入口见 `../docs/`。
