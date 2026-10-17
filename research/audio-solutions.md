# 音频方案调研结果

## Switch音频服务架构

### 核心服务
- **audout** - 音频输出服务
- **audin** - 音频输入服务（麦克风）
- **audren** - 音频渲染服务（混音、效果处理）

### 模拟器实现参考
- **Yuzu**: 完整的audren实现，支持音效DSP
- **Ryujinx**: 轻量级实现，专注基础播放

## Android音频后端对比

### AAudio (推荐)
- **发布**: Android 8.0+ (API 26)
- **优势**: 
  - 最低延迟 (< 10ms)
  - 专为游戏设计
  - 简单API
- **许可**: Apache 2.0 (GPL兼容)
- **ARM64优化**: 原生支持

### OpenSL ES (备选)
- **发布**: Android 2.3+ (API 9)
- **优势**: 更广泛的设备支持
- **劣势**: API复杂，延迟略高

### Oboe (Google推荐包装库)
- **特点**: 自动选择AAudio/OpenSL ES
- **许可**: Apache 2.0
- **集成**: 单头文件，易集成
- **推荐**: ✅ 最佳选择

## 音频重采样/混音库

### libsamplerate
- **质量**: 行业标准
- **许可**: BSD-2 (GPL兼容)
- **NEON**: 有优化版本

### SpeexDSP
- **特点**: 回声消除 + 重采样
- **许可**: BSD-3 (GPL兼容)
- **用途**: 如需语音输入

### 内置Android Resampler
- **位置**: frameworks/av/media/libaudioprocessing
- **优势**: 系统原生，已优化
- **考虑**: 可能无需额外库

## 推荐技术栈

```
Switch audout/audin/audren
         ↓
   服务适配层 (cmd解析)
         ↓
     混音/重采样
         ↓
       Oboe
         ↓
   AAudio/OpenSL ES
         ↓
     Android HAL
```

## 工作量估算

- **基础播放** (audout): 40-80小时
- **音频渲染** (audren混音): 100-200小时
- **输入支持** (audin): 30-60小时
- **总计**: 170-340小时（阶段3优先级较低）

## 集成建议

1. **最小可行**: 只实现audout基础播放，使用Oboe
2. **完整体验**: 加上audren混音，参考Ryujinx实现
3. **延迟优化**: 调整缓冲区大小，目标<20ms

## 参考资源

- switchbrew.org/wiki/Audio_services
- Ryujinx: `Ryujinx.HLE/HOS/Services/Audio/`
- Yuzu: `src/core/hle/service/audio/`
- Oboe: github.com/google/oboe
