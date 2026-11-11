# 本地参考源码与分析输入

平台实现与相关第三方源码已分别归入 `../android/` 与 `../windows/`；本目录只保留不再属于平台构建入口的本地参考材料。

- `d3-symbols/`：当前 guest 匹配的 SDK 符号表。
- `tools/`：本地资源处理工具，构建产物和游戏输入不放在这里。
- `d2r-mobile/`：保留的早期兼容层参考源文件，不是当前编译入口。
- `legacy-recovery/`：原有源码恢复快照，保留原字节及来源说明，不参加正式构建。

已迁出：Windows 上游工作树在 `../windows/source/ScarletNX-src/`（可重建补丁见 `../windows/patches/`），Android GPU 固定版本源码在 `../android/third_party/eden/`（本地改动由 `../android/gpu/patches/` 记录）。

游戏资源、guest、签名和存档统一在 `../local/`；生成结果统一在 `../out/`。平台入口见 `../android/`、`../windows/`，跨平台索引见 `../docs/`。
