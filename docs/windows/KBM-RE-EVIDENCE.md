# D3 原生键鼠：RE 证据（B0）

日期：2026-10-31。范围：Windows ScarletNX 运行时。B0 只做地址基线和探针，不改游戏/运行时。

## 1. 输入身份

| 项 | 值 |
| --- | --- |
| 游戏 | Diablo III: Eternal Collection，`01001B300B9BE000` |
| 游戏版本 | `2.6.2.52309` |
| main NSO build id | `2607A74F5DF7754CC0357B5DF7E496931355D8CA` |
| `main.nso0` SHA-256 | `B6487A316F8BF5B92D26C07C5E9A75AA4654CF325E2EAF033A083253D511F267` |
| `01001B300B9BE000_code.dll` SHA-256 | `A829DCE8AC2554A44DF087132CF9D266582010280C660D32A958642C8B7BDA51` |
| `libd3guest.so` SHA-256（Android 参考镜像） | `DD050EF63CBAEAAEAE9F7C842B26456A05D7482AAF9B91103A9BF0E0188625A2` |
| `d3_main.elf` SHA-256（B0 生成物） | `3E35731A5FADA4BF1B276F42E704FAD40C2D7AE3D436B283947817B634998320` |

## 2. 运行时 guest 模块

Frida 通过 `01001B300B9BE000_code.dll!snx_module` 读取：

| 模块 | guest base | size | text | rodata | data |
| --- | --- | --- | --- | --- | --- |
| `rtld` | `0x8000000` | `0x4000` | `0x1a00` | `0xd20` | `0x280` |
| `main` | `0x8005000` | `0x1aa7000` | `0xc72b90` | `0x4249c4` | `0xc4a14` |
| `sdk` | `0x9aac000` | `0xcfb000` | `0x5407d0` | `0x6985e8` | `0x61fb0` |

`snx_module.abi = 11`。

guest 内存在宿主进程里是**视图拷贝**，不是直接映射到 `0x8005000`。B0 的定位方法：

1. 读 `SnxModInfo.main.base/size`；
2. 找 `Process.enumerateRanges('rw-')` 中 `size == main.size` 的视图；
3. 视图基址 + NSO 偏移 = 宿主地址；该偏移同时就是 **guest offset**（对 main 而言）。
4. `guest_address = main.base + offset`。

## 3. 已定位的 PC 输入/UI 字符串

通过 Frida 扫描 main 视图确认，值均为原始字符串：

| 字符串 | guest address | NSO 文件偏移 |
| --- | --- | --- |
| `LeftClickToMove` | `0x8dc985b` | `0xdc495b` |
| `RightClickAttack` | `0x8e26e0b` | `0xe21f0b` |
| `UseCommandClickAsRightClick` | `0x8e4533b` | `0xe4043b` |
| `UI_HUD_ClickPredicate` | `0x8dcf212` | `0xdca312` |
| `ControlScheme` | `0x8dc91cb` | `0xdc42cb` |
| `ActionBinding` | `0x8ecc112` | `0xec7212` |

`ActionBinding` 后面紧接 protobuf 描述：`key_1`、`key_modifier_flags_1`、`key_2`、`key_modifier_flags_2`，说明 Switch 包里保留了 PC 键位绑定的数据结构。

## 4. 重要负结果

D3 的 main 模块**没有**导入/调用 `GetMouseStates` / `GetKeyboardStates`：

- `guest_relocs.h` 的 main 导入只有 Npad、SixAxis、swkbd 等；
- `main.nso0` 的字符串表没有 `GetMouseStates`；
- `libd3guest.so` 里有 SDK 的 `GetMouseStates` 实现，但 main 没有直接 BL 调用，也没有对应导入槽。

因此：

- **不要**把 `hid.c:430` 的全零鼠标环当成主路径；
- 原生键鼠必须走 **UI 消息注入**、**游戏动作/点击入口**，或把游戏切到 PC 控制模式；
- D2R 的 `dm_cursor.c` / `dm_world.c` 是正确参照。

## 5. 工具与复现

```powershell
# 1) 解 NSO（用户自备 hactool）
hactool -t nso --uncompressed=main.bin main.nso0

# 2) 生成 Ghidra 可加载 ELF
python tools/d3-re/build_main_elf.py main.bin --out out/windows/kbm/b0/d3_main.elf

# 3) Frida 读 guest 字符串（spawn 一个临时进程，读完即杀）
python tools/d3-re/frida_probe.py --json

# 4) Ghidra（8G 堆）
.\tools\d3-re\ghidra_analyze.ps1 -Elf .\out\windows\kbm\b0\d3_main.elf `
  -GhidraHome <ghidra_12.1.4_PUBLIC> -JavaHome <jdk-21>
```

B0 验收：`frida_probe.py --json` 能打印上表 guest 地址和字符串值；`d3_main.elf` 能被 `llvm-readelf` 识别为 AArch64 ELF。

## 6. 未完成 / B1 入口

- Ghidra 全量分析在 8G 堆下仍在跑；若某函数导致卡住，改用定向分析或缩小函数范围，不能把“分析超时”当成“功能不存在”。
- B1 要找：
  - Npad polling → action mapping；
  - `LeftClickToMove` / `RightClickAttack` 的动作分发；
  - UI 根控件/消息处理；
  - 键盘动作/文本输入。
- 下一步是只读探针：先读全局/函数指针，不写游戏内存。

## 7. 安全

- 未写存档、未改 `_code.dll`、未改安装目录 exe。
- Frida 探针默认 spawn 后 kill；`--keep` 才会留下进程。
- 所有二进制分析产物在 `out/`（git-ignored）。
