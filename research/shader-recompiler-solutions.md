# Shader重编译器调研结果

## SPIR-V生成库对比

### 1. sirit ⭐ 主要推荐

**GitHub**: https://github.com/ReinUsesLisp/sirit  
**许可证**: BSD-3-Clause - ✅ GPL-3.0兼容  
**语言**: C++ | **活跃度**: 2026-08-15更新

**特点**:
- 运行时SPIR-V汇编器，无需外部工具
- 自动处理声明排序、类型/常量去重
- **Yuzu使用的就是这个库**
- 轻量级，专注设计
- 完美适合从自定义IR动态生成代码

**优势**:
- ✅ 正是为运行时shader生成设计
- ✅ API清晰，减少手写SPIR-V二进制的错误
- ✅ 已在多个模拟器中验证

**劣势**:
- 早期阶段，部分指令需手动编写

**节省工作量**: 20-30小时（相比手写SPIR-V）

---

### 2. SPIRV-Tools (辅助验证)

**GitHub**: https://github.com/KhronosGroup/SPIRV-Tools  
**许可证**: Apache-2.0 - ✅ GPL-3.0兼容  
**维护**: Khronos官方

**用途**:
- SPIR-V汇编器/反汇编器/验证器/优化器
- 行业标准，支持SPIR-V 1.0-1.5

**推荐用法**: 生成后验证和优化，不作为主要生成工具

---

### 3. 其他库（不适用）

| 库 | 用途 | 为何不适用 |
|----|------|-----------|
| SPIRV-Cross | SPIR-V→GLSL/HLSL | 我们要生成SPIR-V，不是反编译 |
| glslang | GLSL→SPIR-V | 我们从二进制SASS开始，不是高级语言 |
| shaderc | GLSL/HLSL编译 | 同上 |

---

## Maxwell SASS解析参考

### rNdN 项目

**GitHub**: https://github.com/akrolik/rNdN  
**许可证**: MIT - ✅ GPL-3.0兼容  
**语言**: C++

**提供**:
- 详细的Maxwell SASS指令树
- 二进制解析工具（BinaryUtils.h, Instruction.h）
- 谓词指令和控制流支持

**限制**:
- 为数据库查询编译优化，不是图形shader

**用途**: 作为Maxwell SASS二进制格式和指令定义的参考

---

## 现有方案对比

### Eden (我们已有的239文件)
- **优势**: 经过实战验证，支持Switch游戏
- **集成成本**: 150-400h（ROADMAP估算）
- **推荐**: 作为主要源码

### Skyline
- **状态**: 活跃但shader编译器文档少
- **观察**: 可能使用嵌入式/自定义重编译器

### Yuzu (历史)
- **架构**: 使用sirit生成SPIR-V + 自定义Maxwell解码器
- **许可**: GPL-3.0兼容
- **状态**: 仓库已下线

### Ryujinx (历史)
- **语言**: C#
- **相关性**: 架构难以分解为C++复用

---

## 推荐技术栈

```
Maxwell SASS二进制
       ↓
【Maxwell解码器】← Eden的实现
       ↓
  自定义IR (中间表示)
       ↓
【SPIR-V生成】← sirit库 ⭐
       ↓
【验证/优化】← SPIRV-Tools
       ↓
    SPIR-V二进制
       ↓
  Vulkan管线
```

---

## 工作量重估

### 原估算: 150-400小时

### 可能的减少:
- **使用sirit** (vs 手写SPIR-V): -20-30h
- **复用Eden的Maxwell解码器**: 0h (原本就计划这样)
- **参考rNdN的SASS指令定义**: -10-15h

### 修正估算: **130-380小时**

**关键洞察**: 大部分工作是**Maxwell二进制解析 + 语义翻译到IR**，不是SPIR-V生成。sirit优化的是最后10-15%（发射），不是85%（解析+翻译）。

---

## 实施建议

### 阶段1: 基础集成 (40-80h)
1. 提取Eden的shader_recompiler（239文件）
2. 集成sirit库
3. 编译测试，确保依赖解决

### 阶段2: 适配Android (30-60h)
1. 移除PC特定依赖
2. 适配ARM64/NEON优化
3. 调整内存管理（Android约束）

### 阶段3: 验证管线 (40-120h)
1. 添加SPIRV-Tools验证
2. 测试简单shader（顶点、片段）
3. 修复生成的SPIR-V问题

### 阶段4: 完整支持 (20-120h)
1. 支持复杂shader特性
2. 几何/计算shader（如果D3使用）
3. 性能优化

**关键依赖**: 完成阶段1.2，有真实nvdrv调用后才能测试

---

## 许可证兼容性

| 组件 | 许可证 | GPL-3.0兼容 |
|------|--------|------------|
| sirit | BSD-3-Clause | ✅ |
| SPIRV-Tools | Apache-2.0 | ✅ |
| rNdN | MIT | ✅ |
| Eden | GPL-3.0 | ✅ |

所有推荐组件都与GPL-3.0兼容。

---

## 关键资源

- **sirit API**: https://github.com/ReinUsesLisp/sirit
- **rNdN Maxwell指令**: https://github.com/akrolik/rNdN/tree/main/include/SASS/Tree/Instructions/Maxwell
- **SPIR-V规范**: https://github.com/KhronosGroup/SPIRV-Tools/blob/main/docs/binary-layout.md

---

## 决策建议

### 立即决定 ✅
- 使用Eden的shader_recompiler作为基础
- 集成sirit替代手写SPIR-V
- 添加SPIRV-Tools验证层

### 优化机会 💡
- 分析D3实际使用的shader特性
- 可能只需要实现完整Maxwell指令集的子集
- 专注于D3需要的shader类型（顶点/片段优先）

### 风险缓解 ⚠️
- Eden代码质量未知（需要评估）
- 可能需要大量调试
- ARM64特定问题可能出现

**总结**: 没有魔法银弹可以消除150-400h估算，但sirit + rNdN参考可以略微优化。核心工作是Maxwell语义理解和翻译，这是不可避免的。
