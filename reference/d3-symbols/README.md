# Guest 符号资料

`sdk.symbols.json` 保存与当前 Android guest 匹配的更新版 SDK 动态符号偏移，供 `sdk_sym.py`、`resolve_guest.py`、`gen_guest_relocs.py` 使用。它是分析输入，不是构建缓存；请保留。

guest 原件位于 `local/android/libd3guest.so`，基础版与更新版的 ExeFS 分别保存在 `local/assets/exefs/`、`local/assets/exefs_update/`。更新版 SDK 在合并 guest 中的虚拟基址为 `0x10000`；不要将基础版符号直接用于更新版 guest。

重新分析已解压的 NSO0 文件：

```powershell
python -I android/tools/nso_symbols.py local/assets/exefs_update/sdk.nso0
```

结果默认写入 `out/android/symbols/`，不会覆盖这里的基线。实际 hook 行为以 `android/host/` 当前源码与测试为准，旧报告中的地址表不作为接口规范。
