# 输入处理(HID)方案

## Switch HID服务架构

### 核心接口
- **hid:u** - 用户态HID服务（游戏主要使用）
- **hid:sys** - 系统HID服务（系统功能）
- **hid:dbg** - 调试接口
- **400+命令** 覆盖所有输入设备

### 输入设备类型
1. **Npad** (Controller) - 控制器输入，D3主要使用
2. **Touch** - 触摸屏（菜单导航）
3. **Keyboard/Mouse** - 支持但优先级低
4. **SixAxisSensor** - 陀螺仪/加速度计（运动控制）

### 共享内存架构
```
HID共享内存结构:
├── Header
├── Npad[8] LIFO环形缓冲区  ← 每个控制器
│   ├── 按钮状态（64位位域）
│   ├── 模拟摇杆（左/右，X/Y）
│   ├── 连接状态
│   └── 电池电量
├── Touch LIFO缓冲区
└── SixAxis LIFO缓冲区
```

**关键特性**:
- **LIFO环形缓冲区**: 低延迟输入读取
- **无锁设计**: Guest直接读取共享内存
- **250Hz轮询率**: 游戏响应性

---

## Android输入系统映射

### GameController API

**核心类**:
```java
// 物理控制器
GameController.getControllerIds()
KeyEvent - 按钮事件
MotionEvent - 摇杆/扳机事件
```

**按钮映射挑战**:
```
Android (Xbox布局)    Switch布局
    A                   B
    B                   A
    X                   Y
    Y                   X
```
⚠️ **必须重新映射**，否则A/B和X/Y功能对调！

### 传感器API

**运动控制**:
```java
SensorManager
  ├── TYPE_GYROSCOPE     - 陀螺仪
  └── TYPE_ACCELEROMETER - 加速度计
```

**坐标系转换**:
- Android和Switch使用不同的坐标系
- 需要旋转矩阵转换
- 目标：200Hz采样率

### 触摸输入

```java
View.onTouchEvent(MotionEvent)
  - 支持多点触控（最多10点）
  - 用于UI导航和虚拟按键
```

---

## D3最小实现

### 阶段1: 启动支持 (40-80h)

**必须实现的命令**:
- **Cmd 103**: ActivateNpad - 激活控制器子系统
- **Cmd 100**: GetSharedMemoryHandle - 分配共享内存
- **Cmd 102**: SetSupportedNpadStyleSet - 设置支持的控制器类型

**共享内存**:
```c
// 必须匹配Switch布局
struct NpadState {
    uint64_t sampling_number;
    uint64_t buttons;           // 位域: A=0x1, B=0x2, X=0x4, Y=0x8
    int32_t lstick_x, lstick_y; // -32768 到 32767
    int32_t rstick_x, rstick_y;
    // ... 其他字段
};
```

### 阶段2: 基础控制 (60-100h)

**JNI桥接**:
```java
// InputManager.java
public void onGenericMotionEvent(MotionEvent event) {
    float lx = event.getAxisValue(AXIS_X);
    float ly = event.getAxisValue(AXIS_Y);
    // 转换为Switch格式
    int lx_switch = (int)(lx * 32767.0f);
    int ly_switch = (int)(ly * 32767.0f);
    // 调用Native
    updateAnalogStick(0, lx_switch, ly_switch);
}
```

**Native处理**:
```c
// d3_hid.c
void d3_hid_update_button(uint8_t npad_id, uint64_t buttons) {
    NpadState* state = &g_hid_shared_memory->npad[npad_id];
    state->buttons = buttons;
    state->sampling_number++;
}
```

### 阶段3: 运动控制 (60-100h)

**陀螺仪数据**:
```java
// 传感器监听
SensorEventListener listener = new SensorEventListener() {
    public void onSensorChanged(SensorEvent event) {
        if (event.sensor.getType() == TYPE_GYROSCOPE) {
            float gx = event.values[0]; // rad/s
            float gy = event.values[1];
            float gz = event.values[2];
            updateSixAxis(gx, gy, gz, ...);
        }
    }
};
```

### 阶段4: 高级特性 (60-80h)

- 多控制器支持（最多8个）
- 触摸屏虚拟按钮
- 控制器重映射UI
- 振动/触觉反馈

---

## 集成到现有代码

### 1. 服务注册 (d3_service.c)

```c
// 添加到port_kind()
case PORT_HID:
    return D3_IF_HID;

// 添加到domain_command()
case D3_IF_HID:
    hid_command(msg, obj);
    break;
```

### 2. HID命令处理器

```c
// 新文件: d3_hid.c
static void hid_command(Message* msg, Object* obj) {
    switch (msg->cmd) {
    case 100: // GetSharedMemoryHandle
        reply_handle(msg, g_hid_shared_memory_handle);
        break;
    case 103: // ActivateNpad
        g_npad_active = true;
        reply_result(msg, 0);
        break;
    // ... 更多命令
    }
}
```

### 3. JNI入口点 (d3_jni.c)

```c
JNIEXPORT void JNICALL
Java_com_d3mobile_InputManager_updateButton(
    JNIEnv* env, jobject thiz, jint npad_id, jlong buttons) {
    d3_hid_update_button((uint8_t)npad_id, (uint64_t)buttons);
}
```

---

## 按钮映射表

### Switch按钮位域

```c
#define SWITCH_A       (1ULL << 0)
#define SWITCH_B       (1ULL << 1)
#define SWITCH_X       (1ULL << 2)
#define SWITCH_Y       (1ULL << 3)
#define SWITCH_LSTICK  (1ULL << 4)
#define SWITCH_RSTICK  (1ULL << 5)
#define SWITCH_L       (1ULL << 6)
#define SWITCH_R       (1ULL << 7)
#define SWITCH_ZL      (1ULL << 8)
#define SWITCH_ZR      (1ULL << 9)
#define SWITCH_PLUS    (1ULL << 10)
#define SWITCH_MINUS   (1ULL << 11)
#define SWITCH_DLEFT   (1ULL << 12)
#define SWITCH_DUP     (1ULL << 13)
#define SWITCH_DRIGHT  (1ULL << 14)
#define SWITCH_DDOWN   (1ULL << 15)
```

### Android → Switch映射

```java
// 重映射函数
private long mapAndroidToSwitch(int keyCode) {
    switch (keyCode) {
        case KEYCODE_BUTTON_A:      return SWITCH_B;  // 交换!
        case KEYCODE_BUTTON_B:      return SWITCH_A;  // 交换!
        case KEYCODE_BUTTON_X:      return SWITCH_Y;  // 交换!
        case KEYCODE_BUTTON_Y:      return SWITCH_X;  // 交换!
        case KEYCODE_BUTTON_L1:     return SWITCH_L;
        case KEYCODE_BUTTON_R1:     return SWITCH_R;
        case KEYCODE_BUTTON_L2:     return SWITCH_ZL;
        case KEYCODE_BUTTON_R2:     return SWITCH_ZR;
        case KEYCODE_BUTTON_START:  return SWITCH_PLUS;
        case KEYCODE_BUTTON_SELECT: return SWITCH_MINUS;
        // ... 更多映射
    }
}
```

---

## 工作量估算

| 阶段 | 描述 | 工作量 |
|------|------|--------|
| 阶段1 | 启动支持（命令存根） | 40-80h |
| 阶段2 | 基础控制（按钮+摇杆） | 60-100h |
| 阶段3 | 运动控制（陀螺仪） | 60-100h |
| 阶段4 | 高级特性（多控制器） | 60-80h |
| **最小可行** | 仅阶段1+2 | 100-180h |
| **完整方案** | 全部4阶段 | 220-360h |

---

## 测试设备支持

### Galaxy Tab S8 (Adreno 730)

**输入能力**:
- ✅ 蓝牙控制器支持（Xbox/PS4/PS5）
- ✅ 触摸屏（10点多触控）
- ✅ 陀螺仪（ICM-42607）
- ✅ 加速度计（200Hz采样）
- ✅ USB-C有线控制器

**推荐控制器**:
- Xbox Wireless Controller（最佳兼容）
- DualSense（PS5，完整支持）
- Switch Pro Controller（蓝牙，可能需要配对工具）

---

## 参考资源

### 官方文档
- **switchbrew.org/wiki/HID_services** - 协议文档
- **libnx hid.h** - 结构定义

### 模拟器实现
- **Yuzu**: `src/core/hle/service/hid/`
- **Ryujinx**: `Ryujinx.HLE/HOS/Services/Hid/`
- **Skyline**: `app/src/main/cpp/skyline/services/hid/`

### Android文档
- **Game Controllers**: developer.android.com/training/game-controllers

---

## 实施优先级

### 当前阶段（1.2）
- ⏸️ **不阻塞**: HID属于阶段3，图形优先

### 如果HID请求出现在启动时
- ✅ **实现阶段1存根**: 返回成功，分配空共享内存
- ✅ **记录命令**: 日志guest请求的HID命令

### 阶段2完成后
- ✅ **实现完整HID**: 按上述4阶段逐步推进

---

## 关键设计决策

### 1. 共享内存分配
```c
// 使用Android ashmem或匿名mmap
int fd = ashmem_create_region("d3-hid-shared", HID_SHARED_SIZE);
void* addr = mmap(NULL, HID_SHARED_SIZE, PROT_READ|PROT_WRITE, 
                   MAP_SHARED, fd, 0);
g_hid_shared_memory = (HIDSharedMemory*)addr;
```

### 2. 线程模型
- **选项A**: 在guest线程中直接更新共享内存（推荐）
- **选项B**: 专用输入线程 + 队列（更复杂）

### 3. 触摸屏处理
- **优先**: 物理控制器支持
- **备选**: 屏幕虚拟按钮（触摸区域→按钮事件）

---

## 已知问题与解决方案

### 问题1: 控制器检测延迟
**症状**: 连接后2-3秒才识别  
**原因**: Android蓝牙配对握手  
**解决**: 启动时预连接，缓存控制器ID

### 问题2: 陀螺仪漂移
**症状**: 运动控制逐渐偏移  
**原因**: 传感器噪声累积  
**解决**: 定期重新校准，零速度检测

### 问题3: 按钮映射混乱
**症状**: A/B功能对调  
**原因**: Android使用Xbox布局  
**解决**: 见上述映射表，必须重映射

---

## 下一步行动

### 立即（阶段1.2期间）
- 如果guest启动请求HID，添加存根
- 在`d3_service.c`中注册PORT_HID

### 阶段2完成后
1. 实现阶段1（启动支持）
2. 添加JNI桥接到MainActivity
3. 实现阶段2（按钮+摇杆）
4. 用真实控制器测试

### 长期优化
- 多控制器支持
- 运动控制
- 触摸屏虚拟控制器
- 振动反馈
