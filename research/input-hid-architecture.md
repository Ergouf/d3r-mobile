# Switch HID Service → Android Input Architecture Research

**Purpose**: Research findings for implementing Stage 3 input handling (hid service) in the Diablo III Switch-to-Android compatibility layer.

**Date**: 2026-10-16

---

## Executive Summary

Switch games access controller input through the `hid` system service, which provides:
- Physical controller state (buttons, analog sticks, triggers)
- Motion sensors (gyroscope, accelerometer)
- Touch screen input
- Vibration/haptics

Android provides input through:
- GameController API for physical controllers
- MotionEvent for touch and sensors
- SensorManager for motion data

The compatibility layer must translate Switch HID service calls to Android input APIs.

---

## 1. Switch HID Service Architecture

### 1.1 Service Interface

The Switch HID service (`hid`) provides these primary interfaces:

**Service Names**:
- `hid` - Main HID service
- `hid:dbg` - Debug interface
- `hid:sys` - System interface
- `irs` - IR camera service
- `irs:sys` - IR system service

**Key Commands** (based on Switch OS 12.x):
```
IHidServer (hid service):
  Cmd 0: CreateAppletResource - Initialize HID for application
  Cmd 1: ActivateDebugPad
  Cmd 11: ActivateTouchScreen
  Cmd 21: ActivateMouse
  Cmd 31: ActivateKeyboard
  Cmd 40: AcquireXpadIdEventHandle
  Cmd 41: ReleaseXpadIdEventHandle
  Cmd 51: ActivateXpad
  Cmd 55: GetXpadIds
  Cmd 56: ActivateJoyXpad
  Cmd 58: GetJoyXpadLifoHandle
  Cmd 59: GetJoyXpadIds
  Cmd 60: ActivateSixAxisSensor
  Cmd 61: DeactivateSixAxisSensor
  Cmd 62: GetSixAxisSensorLifoHandle
  Cmd 63: ActivateJoySixAxisSensor
  Cmd 64: DeactivateJoySixAxisSensor
  Cmd 65: GetJoySixAxisSensorLifoHandle
  Cmd 66: StartSixAxisSensor
  Cmd 67: StopSixAxisSensor
  Cmd 68: IsSixAxisSensorFusionEnabled
  Cmd 69: EnableSixAxisSensorFusion
  Cmd 70: SetSixAxisSensorFusionParameters
  Cmd 71: GetSixAxisSensorFusionParameters
  Cmd 72: ResetSixAxisSensorFusionParameters
  Cmd 73: SetAccelerometerParameters
  Cmd 74: GetAccelerometerParameters
  Cmd 75: ResetAccelerometerParameters
  Cmd 76: SetAccelerometerPlayMode
  Cmd 77: GetAccelerometerPlayMode
  Cmd 78: ResetAccelerometerPlayMode
  Cmd 79: SetGyroscopeZeroDriftMode
  Cmd 80: GetGyroscopeZeroDriftMode
  Cmd 81: ResetGyroscopeZeroDriftMode
  Cmd 82: IsSixAxisSensorAtRest
  Cmd 83: IsFirmwareUpdateAvailableForSixAxisSensor
  Cmd 91: ActivateGesture
  Cmd 100: SetSupportedNpadStyleSet
  Cmd 101: GetSupportedNpadStyleSet
  Cmd 102: SetSupportedNpadIdType
  Cmd 103: ActivateNpad
  Cmd 104: DeactivateNpad
  Cmd 106: AcquireNpadStyleSetUpdateEventHandle
  Cmd 107: DisconnectNpad
  Cmd 108: GetPlayerLedPattern
  Cmd 109: ActivateNpadWithRevision
  Cmd 120: SetNpadJoyHoldType
  Cmd 121: GetNpadJoyHoldType
  Cmd 122: SetNpadJoyAssignmentModeSingleByDefault
  Cmd 123: SetNpadJoyAssignmentModeSingle
  Cmd 124: SetNpadJoyAssignmentModeDual
  Cmd 125: MergeSingleJoyAsDualJoy
  Cmd 126: StartLrAssignmentMode
  Cmd 127: StopLrAssignmentMode
  Cmd 128: SetNpadHandheldActivationMode
  Cmd 129: GetNpadHandheldActivationMode
  Cmd 130: SwapNpadAssignment
  Cmd 131: IsUnintendedHomeButtonInputProtectionEnabled
  Cmd 132: EnableUnintendedHomeButtonInputProtection
  Cmd 133: SetNpadJoyAssignmentModeSingleWithDestination
  Cmd 134: SetNpadAnalogStickUseCenterClamp
  Cmd 135: SetNpadCaptureButtonAssignment
  Cmd 136: ClearNpadCaptureButtonAssignment
  Cmd 200: GetVibrationDeviceInfo
  Cmd 201: SendVibrationValue
  Cmd 202: GetActualVibrationValue
  Cmd 203: CreateActiveVibrationDeviceList
  Cmd 204: PermitVibration
  Cmd 205: IsVibrationPermitted
  Cmd 206: SendVibrationValues
  Cmd 207: SendVibrationGcErmCommand
  Cmd 208: GetActualVibrationGcErmCommand
  Cmd 209: BeginPermitVibrationSession
  Cmd 210: EndPermitVibrationSession
  Cmd 300: ActivateConsoleSixAxisSensor
  Cmd 301: StartConsoleSixAxisSensor
  Cmd 302: StopConsoleSixAxisSensor
  Cmd 303: ActivateSevenSixAxisSensor
  Cmd 304: StartSevenSixAxisSensor
  Cmd 305: StopSevenSixAxisSensor
  Cmd 306: InitializeSevenSixAxisSensor
  Cmd 307: FinalizeSevenSixAxisSensor
  Cmd 308: SetSevenSixAxisSensorFusionStrength
  Cmd 309: GetSevenSixAxisSensorFusionStrength
  Cmd 400: IsUsbFullKeyControllerEnabled
  Cmd 401: EnableUsbFullKeyController
  Cmd 402: IsUsbFullKeyControllerConnected
```

### 1.2 Shared Memory Structure

HID uses shared memory (LIFO buffers) for low-latency input reading:

**Key Shared Memory Sections**:
- Debug Pad state
- Touch Screen state  
- Mouse state
- Keyboard state
- Npad (controller) state - **Most important for Diablo III**
- Six-Axis Sensor state (gyro/accel)
- Gesture state

**LIFO Buffer Format** (example for Npad):
```c
struct HidNpadSharedMemoryEntry {
    u64 sampling_number;
    u64 buttons;           // Button bitfield
    s32 l_stick_x;         // Left analog X (-32768 to 32767)
    s32 l_stick_y;         // Left analog Y
    s32 r_stick_x;         // Right analog X
    s32 r_stick_y;         // Right analog Y
    u32 connection_state;  // Connected/Wired/Wireless flags
    // ... more fields
};

struct HidNpadSharedMemory {
    HidNpadSharedMemoryEntry entries[17]; // Ring buffer
    u64 latest_entry;
    // ... metadata
};
```

**Button Bitfield**:
```c
#define HID_BUTTON_A        (1ULL << 0)
#define HID_BUTTON_B        (1ULL << 1)
#define HID_BUTTON_X        (1ULL << 2)
#define HID_BUTTON_Y        (1ULL << 3)
#define HID_BUTTON_LSTICK   (1ULL << 4)
#define HID_BUTTON_RSTICK   (1ULL << 5)
#define HID_BUTTON_L        (1ULL << 6)
#define HID_BUTTON_R        (1ULL << 7)
#define HID_BUTTON_ZL       (1ULL << 8)
#define HID_BUTTON_ZR       (1ULL << 9)
#define HID_BUTTON_PLUS     (1ULL << 10)
#define HID_BUTTON_MINUS    (1ULL << 11)
#define HID_BUTTON_LEFT     (1ULL << 12)
#define HID_BUTTON_UP       (1ULL << 13)
#define HID_BUTTON_RIGHT    (1ULL << 14)
#define HID_BUTTON_DOWN     (1ULL << 15)
#define HID_BUTTON_LSTICK_LEFT  (1ULL << 16)
#define HID_BUTTON_LSTICK_UP    (1ULL << 17)
#define HID_BUTTON_LSTICK_RIGHT (1ULL << 18)
#define HID_BUTTON_LSTICK_DOWN  (1ULL << 19)
#define HID_BUTTON_RSTICK_LEFT  (1ULL << 20)
#define HID_BUTTON_RSTICK_UP    (1ULL << 21)
#define HID_BUTTON_RSTICK_RIGHT (1ULL << 22)
#define HID_BUTTON_RSTICK_DOWN  (1ULL << 23)
#define HID_BUTTON_SL       (1ULL << 24)
#define HID_BUTTON_SR       (1ULL << 25)
// More for Pro Controller special buttons
```

### 1.3 Six-Axis Sensor Data

```c
struct SixAxisSensorState {
    u64 delta_time;       // Microseconds since last sample
    u64 sampling_number;
    float accel_x;        // Accelerometer (m/s²)
    float accel_y;
    float accel_z;
    float gyro_x;         // Gyroscope (rad/s)
    float gyro_y;
    float gyro_z;
    float orientation[9]; // 3x3 rotation matrix
    u32 flags;
};
```

---

## 2. Android Input System

### 2.1 GameController API

**KeyEvent** for button presses:
```java
@Override
public boolean onKeyDown(int keyCode, KeyEvent event) {
    if ((event.getSource() & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD) {
        switch(keyCode) {
            case KeyEvent.KEYCODE_BUTTON_A:      // Switch B position
            case KeyEvent.KEYCODE_BUTTON_B:      // Switch A position  
            case KeyEvent.KEYCODE_BUTTON_X:      // Switch Y position
            case KeyEvent.KEYCODE_BUTTON_Y:      // Switch X position
            case KeyEvent.KEYCODE_BUTTON_L1:     // L
            case KeyEvent.KEYCODE_BUTTON_R1:     // R
            case KeyEvent.KEYCODE_BUTTON_L2:     // ZL
            case KeyEvent.KEYCODE_BUTTON_R2:     // ZR
            case KeyEvent.KEYCODE_BUTTON_THUMBL: // Left stick click
            case KeyEvent.KEYCODE_BUTTON_THUMBR: // Right stick click
            case KeyEvent.KEYCODE_BUTTON_START:  // Plus
            case KeyEvent.KEYCODE_BUTTON_SELECT: // Minus
            case KeyEvent.KEYCODE_DPAD_UP:
            case KeyEvent.KEYCODE_DPAD_DOWN:
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                return true;
        }
    }
    return super.onKeyDown(keyCode, event);
}
```

**MotionEvent** for analog sticks and triggers:
```java
@Override
public boolean onGenericMotionEvent(MotionEvent event) {
    if ((event.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK &&
        event.getAction() == MotionEvent.ACTION_MOVE) {
        
        InputDevice device = event.getDevice();
        
        // Left stick
        float lx = getCenteredAxis(event, device, MotionEvent.AXIS_X);
        float ly = getCenteredAxis(event, device, MotionEvent.AXIS_Y);
        
        // Right stick  
        float rx = getCenteredAxis(event, device, MotionEvent.AXIS_Z);
        float ry = getCenteredAxis(event, device, MotionEvent.AXIS_RZ);
        
        // Triggers (0.0 to 1.0)
        float ltrigger = event.getAxisValue(MotionEvent.AXIS_LTRIGGER);
        float rtrigger = event.getAxisValue(MotionEvent.AXIS_RTRIGGER);
        
        // D-pad on some controllers
        float hatX = event.getAxisValue(MotionEvent.AXIS_HAT_X);
        float hatY = event.getAxisValue(MotionEvent.AXIS_HAT_Y);
        
        return true;
    }
    return super.onGenericMotionEvent(event);
}

private float getCenteredAxis(MotionEvent event, InputDevice device, int axis) {
    InputDevice.MotionRange range = device.getMotionRange(axis, event.getSource());
    if (range != null) {
        float flat = range.getFlat();
        float value = event.getAxisValue(axis);
        if (Math.abs(value) > flat) {
            return value;
        }
    }
    return 0;
}
```

**Device enumeration**:
```java
int[] deviceIds = InputDevice.getDeviceIds();
for (int deviceId : deviceIds) {
    InputDevice device = InputDevice.getDevice(deviceId);
    int sources = device.getSources();
    
    if ((sources & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD ||
        (sources & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
        // This is a game controller
        String name = device.getName();
        int vendorId = device.getVendorId();
        int productId = device.getProductId();
    }
}
```

### 2.2 Motion Sensors (SensorManager)

```java
SensorManager sensorManager = (SensorManager) getSystemService(Context.SENSOR_SERVICE);
Sensor gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
Sensor accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
Sensor gameRotation = sensorManager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR);

SensorEventListener listener = new SensorEventListener() {
    @Override
    public void onSensorChanged(SensorEvent event) {
        if (event.sensor.getType() == Sensor.TYPE_GYROSCOPE) {
            // Angular velocity in rad/s
            float gyroX = event.values[0];
            float gyroY = event.values[1];
            float gyroZ = event.values[2];
        } else if (event.sensor.getType() == Sensor.TYPE_ACCELEROMETER) {
            // Acceleration in m/s² (including gravity)
            float accelX = event.values[0];
            float accelY = event.values[1];
            float accelZ = event.values[2];
        }
    }
    
    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {}
};

sensorManager.registerListener(listener, gyroscope, SensorManager.SENSOR_DELAY_GAME);
sensorManager.registerListener(listener, accelerometer, SensorManager.SENSOR_DELAY_GAME);
```

### 2.3 Touch Screen

```java
@Override
public boolean onTouchEvent(MotionEvent event) {
    int action = event.getActionMasked();
    int pointerIndex = event.getActionIndex();
    int pointerId = event.getPointerId(pointerIndex);
    
    switch (action) {
        case MotionEvent.ACTION_DOWN:
        case MotionEvent.ACTION_POINTER_DOWN:
            float x = event.getX(pointerIndex);
            float y = event.getY(pointerIndex);
            // Track touch point
            break;
            
        case MotionEvent.ACTION_MOVE:
            for (int i = 0; i < event.getPointerCount(); i++) {
                // Update all active touch points
            }
            break;
            
        case MotionEvent.ACTION_UP:
        case MotionEvent.ACTION_POINTER_UP:
        case MotionEvent.ACTION_CANCEL:
            // Remove touch point
            break;
    }
    return true;
}
```

---

## 3. Implementation Strategy

### 3.1 Architecture Overview

```
Diablo III Guest (ARM64)
    ↓
HID Service Calls (IPC)
    ↓
d3_hid_service.c (compatibility layer)
    ↓
├─→ Android GameController (JNI)
├─→ Android SensorManager (JNI)  
└─→ Android TouchScreen (JNI)
```

### 3.2 Core Components

**Component 1: HID Service Handler** (`d3_hid_service.c`)
- Implement IHidServer interface
- Handle shared memory allocation for input state
- Translate commands to Android input queries
- Update shared memory LIFO buffers

**Component 2: JNI Input Bridge** (`d3_input_jni.c`)
- Native methods to query Android input state
- Button/axis state caching
- Sensor data buffering
- Touch event translation

**Component 3: Java Input Manager** (`InputManager.java`)
- Listen for GameController events
- Register sensor listeners
- Handle touch events
- Provide native methods for querying state

**Component 4: Input Mapper** (`d3_input_mapper.c`)
- Map Android button codes to Switch button bitfield
- Convert Android axis values (-1.0 to 1.0) to Switch format (-32768 to 32767)
- Handle button layout differences (Xbox vs Switch positions)
- Apply deadzones and calibration

### 3.3 Minimal Implementation for Diablo III

Diablo III likely uses:
1. **Basic controller input** - Left stick for movement, buttons for actions
2. **Touch screen** - Menu navigation on handheld
3. **Possibly motion controls** - For aim/camera (optional)

**Priority Order**:
1. Implement Npad (controller) activation and state reading
2. Implement shared memory for button/analog state
3. Add Android GameController → Switch button mapping
4. Add touch screen support for menu navigation
5. Add six-axis sensor support (lower priority)

### 3.4 Stub Strategy

For initial boot:
```c
// Minimal stubs to get past initialization
case 103: // ActivateNpad
    // Just return success, allocate shared memory
    return 0;

case 100: // SetSupportedNpadStyleSet  
    // Accept any style set
    return 0;

case 102: // SetSupportedNpadIdType
    // Accept any ID type
    return 0;
```

Then progressively implement:
- Shared memory structure
- Button state updates
- Analog stick updates
- Event handles for input change notifications

---

## 4. Reference Implementations

### 4.1 Yuzu (C++)

Yuzu's HID implementation architecture:
- **Location**: `src/core/hle/service/hid/`
- **Key files**:
  - `hid.cpp/h` - Main service interface
  - `controllers/npad.cpp` - Controller state management
  - `ring_lifo.h` - Shared memory LIFO buffer
  - `controllers/touchscreen.cpp` - Touch handling

**Key patterns**:
- Each controller type has its own class (Npad, TouchScreen, Keyboard, etc.)
- Shared memory is pre-allocated and structured
- Input is polled from the frontend and written to shared memory
- LIFO buffers maintain history (17 entries typical)

### 4.2 Ryujinx (C#)

Similar architecture but in C#:
- **Location**: `Ryujinx.HLE/HOS/Services/Hid/`
- More object-oriented structure
- Uses C# structs for shared memory layout
- Frontend provides input through abstraction layer

### 4.3 Skyline (Android Native)

**Most relevant** since it's Android-based:
- **Location**: Would have been in `app/src/main/cpp/skyline/services/hid/`
- Direct Android integration using JNI
- Native polling of Android input devices
- Likely used similar shared memory approach

**Note**: Skyline project development has stopped, but architectural patterns remain valid.

### 4.4 SDL2 GameController Database

SDL2 maintains a comprehensive controller mapping database:
- **SDL_GameControllerDB**: Maps physical controllers to standard layout
- Handles Xbox vs Switch button differences
- Provides axis calibration data
- Can be adapted for Android → Switch mapping

**Button Mapping** (Xbox → Switch):
```
Android          Xbox        Switch
BUTTON_A    →    A      →    B (confirm in West, cancel in Japan)
BUTTON_B    →    B      →    A  
BUTTON_X    →    X      →    Y
BUTTON_Y    →    Y      →    X
BUTTON_L1   →    LB     →    L
BUTTON_R1   →    RB     →    R
BUTTON_L2   →    LT     →    ZL (trigger)
BUTTON_R2   →    RT     →    ZR (trigger)
```

---

## 5. Code Skeleton

### 5.1 d3_hid_service.c

```c
#include "d3_service.h"
#include <jni.h>
#include <string.h>

// Shared memory structure (simplified)
struct HidNpadState {
    uint64_t sampling_number;
    uint64_t buttons;
    int32_t lstick_x;
    int32_t lstick_y;
    int32_t rstick_x;
    int32_t rstick_y;
    uint32_t connection_state;
};

struct HidSharedMemory {
    struct HidNpadState npad_entries[8][17]; // 8 controllers, 17 history entries
    uint64_t npad_latest[8];
    // Touch, sensor, etc.
};

static struct HidSharedMemory *g_hid_shared_memory = NULL;
static uint64_t g_sampling_counter = 0;

// JNI references (set during init)
static JavaVM *g_jvm = NULL;
static jobject g_input_manager = NULL;
static jmethodID g_method_getButtonState = NULL;
static jmethodID g_method_getAxisValue = NULL;

int d3_hid_init(JNIEnv *env, jobject input_manager) {
    // Allocate shared memory
    g_hid_shared_memory = mmap(NULL, sizeof(struct HidSharedMemory),
                               PROT_READ | PROT_WRITE,
                               MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_hid_shared_memory == MAP_FAILED) {
        return -1;
    }
    memset(g_hid_shared_memory, 0, sizeof(struct HidSharedMemory));
    
    // Cache JNI references
    (*env)->GetJavaVM(env, &g_jvm);
    g_input_manager = (*env)->NewGlobalRef(env, input_manager);
    
    jclass cls = (*env)->GetObjectClass(env, input_manager);
    g_method_getButtonState = (*env)->GetMethodID(env, cls, "getButtonState", "()J");
    g_method_getAxisValue = (*env)->GetMethodID(env, cls, "getAxisValue", "(I)F");
    
    return 0;
}

void d3_hid_update_input(int controller_id) {
    if (controller_id < 0 || controller_id >= 8) return;
    
    JNIEnv *env;
    (*g_jvm)->AttachCurrentThread(g_jvm, &env, NULL);
    
    // Get current input state from Android
    uint64_t buttons = (*env)->CallLongMethod(env, g_input_manager, g_method_getButtonState);
    float lstick_x = (*env)->CallFloatMethod(env, g_input_manager, g_method_getAxisValue, 0);
    float lstick_y = (*env)->CallFloatMethod(env, g_input_manager, g_method_getAxisValue, 1);
    float rstick_x = (*env)->CallFloatMethod(env, g_input_manager, g_method_getAxisValue, 2);
    float rstick_y = (*env)->CallFloatMethod(env, g_input_manager, g_method_getAxisValue, 3);
    
    // Write to shared memory (ring buffer)
    int entry_index = g_sampling_counter % 17;
    struct HidNpadState *state = &g_hid_shared_memory->npad_entries[controller_id][entry_index];
    
    state->sampling_number = g_sampling_counter++;
    state->buttons = buttons;
    state->lstick_x = (int32_t)(lstick_x * 32767.0f);
    state->lstick_y = (int32_t)(lstick_y * 32767.0f);
    state->rstick_x = (int32_t)(rstick_x * 32767.0f);
    state->rstick_y = (int32_t)(rstick_y * 32767.0f);
    state->connection_state = 1; // Connected
    
    g_hid_shared_memory->npad_latest[controller_id] = entry_index;
    
    (*g_jvm)->DetachCurrentThread(g_jvm);
}

int d3_hid_dispatch(int cmd, uint8_t *buf_in, size_t len_in,
                    uint8_t *buf_out, size_t *len_out) {
    switch (cmd) {
        case 0: // CreateAppletResource
            // Return handle to shared memory
            if (*len_out >= 8) {
                *(uint64_t*)buf_out = (uint64_t)g_hid_shared_memory;
                *len_out = 8;
                return 0;
            }
            return -1;
            
        case 100: // SetSupportedNpadStyleSet
            // Accept any style
            *len_out = 0;
            return 0;
            
        case 102: // SetSupportedNpadIdType
            // Accept any ID type
            *len_out = 0;
            return 0;
            
        case 103: // ActivateNpad
            // Enable controller input
            *len_out = 0;
            return 0;
            
        case 106: // AcquireNpadStyleSetUpdateEventHandle
            // Return event handle (stub for now)
            if (*len_out >= 4) {
                *(uint32_t*)buf_out = 0; // Invalid handle for now
                *len_out = 4;
                return 0;
            }
            return -1;
            
        default:
            // Unimplemented
            *len_out = 0;
            return 0x278; // Not implemented error code
    }
}
```

### 5.2 InputManager.java (Android side)

```java
package com.d3mobile.host;

import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.InputDevice;

public class InputManager {
    private long mButtonState = 0;
    private float[] mAxisValues = new float[6]; // LX, LY, RX, RY, LT, RT
    
    // Button bit positions matching Switch HID
    private static final long BUTTON_A = 1L << 0;
    private static final long BUTTON_B = 1L << 1;
    private static final long BUTTON_X = 1L << 2;
    private static final long BUTTON_Y = 1L << 3;
    private static final long BUTTON_L = 1L << 6;
    private static final long BUTTON_R = 1L << 7;
    private static final long BUTTON_ZL = 1L << 8;
    private static final long BUTTON_ZR = 1L << 9;
    private static final long BUTTON_PLUS = 1L << 10;
    private static final long BUTTON_MINUS = 1L << 11;
    private static final long BUTTON_DPAD_LEFT = 1L << 12;
    private static final long BUTTON_DPAD_UP = 1L << 13;
    private static final long BUTTON_DPAD_RIGHT = 1L << 14;
    private static final long BUTTON_DPAD_DOWN = 1L << 15;
    
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD) {
            updateButtonState(keyCode, true);
            return true;
        }
        return false;
    }
    
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD) {
            updateButtonState(keyCode, false);
            return true;
        }
        return false;
    }
    
    private void updateButtonState(int keyCode, boolean pressed) {
        long bit = 0;
        
        // Map Android KeyEvent to Switch button bits
        // NOTE: Xbox layout (Android default) has A/B and X/Y swapped from Switch
        switch (keyCode) {
            case KeyEvent.KEYCODE_BUTTON_A: bit = BUTTON_B; break; // Xbox A → Switch B
            case KeyEvent.KEYCODE_BUTTON_B: bit = BUTTON_A; break; // Xbox B → Switch A
            case KeyEvent.KEYCODE_BUTTON_X: bit = BUTTON_Y; break; // Xbox X → Switch Y
            case KeyEvent.KEYCODE_BUTTON_Y: bit = BUTTON_X; break; // Xbox Y → Switch X
            case KeyEvent.KEYCODE_BUTTON_L1: bit = BUTTON_L; break;
            case KeyEvent.KEYCODE_BUTTON_R1: bit = BUTTON_R; break;
            case KeyEvent.KEYCODE_BUTTON_L2: bit = BUTTON_ZL; break;
            case KeyEvent.KEYCODE_BUTTON_R2: bit = BUTTON_ZR; break;
            case KeyEvent.KEYCODE_BUTTON_START: bit = BUTTON_PLUS; break;
            case KeyEvent.KEYCODE_BUTTON_SELECT: bit = BUTTON_MINUS; break;
            case KeyEvent.KEYCODE_DPAD_LEFT: bit = BUTTON_DPAD_LEFT; break;
            case KeyEvent.KEYCODE_DPAD_UP: bit = BUTTON_DPAD_UP; break;
            case KeyEvent.KEYCODE_DPAD_RIGHT: bit = BUTTON_DPAD_RIGHT; break;
            case KeyEvent.KEYCODE_DPAD_DOWN: bit = BUTTON_DPAD_DOWN; break;
            default: return;
        }
        
        if (pressed) {
            mButtonState |= bit;
        } else {
            mButtonState &= ~bit;
        }
    }
    
    public boolean onGenericMotionEvent(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
            mAxisValues[0] = event.getAxisValue(MotionEvent.AXIS_X);
            mAxisValues[1] = event.getAxisValue(MotionEvent.AXIS_Y);
            mAxisValues[2] = event.getAxisValue(MotionEvent.AXIS_Z);
            mAxisValues[3] = event.getAxisValue(MotionEvent.AXIS_RZ);
            mAxisValues[4] = event.getAxisValue(MotionEvent.AXIS_LTRIGGER);
            mAxisValues[5] = event.getAxisValue(MotionEvent.AXIS_RTRIGGER);
            return true;
        }
        return false;
    }
    
    // Called from native
    public long getButtonState() {
        return mButtonState;
    }
    
    // Called from native: 0=LX, 1=LY, 2=RX, 3=RY, 4=LT, 5=RT
    public float getAxisValue(int axis) {
        if (axis >= 0 && axis < mAxisValues.length) {
            return mAxisValues[axis];
        }
        return 0.0f;
    }
}
```

---

## 6. Integration with Existing d3_host

### 6.1 Service Registration

Add to `d3_service.c`:
```c
extern int d3_hid_dispatch(int cmd, uint8_t *buf_in, size_t len_in,
                          uint8_t *buf_out, size_t *len_out);

// In service dispatch table
{"hid", d3_hid_dispatch},
{"hid:dbg", d3_hid_dispatch}, // Same handler, debug variant
{"hid:sys", d3_hid_dispatch}, // System variant
```

### 6.2 Initialization

Add to MainActivity.java onCreate():
```java
InputManager inputManager = new InputManager();

// Pass to native during d3_host_init
nativeInitInput(inputManager);
```

### 6.3 Update Loop

Input should be polled regularly:
```java
// In a dedicated input thread or main render loop
new Thread(() -> {
    while (running) {
        nativeUpdateInput(); // Calls d3_hid_update_input internally
        Thread.sleep(4); // ~250Hz polling
    }
}).start();
```

Or use event-driven approach with callbacks from Java to native.

---

## 7. Testing Strategy

### 7.1 Standalone Tests

Create `test_hid.c`:
```c
// Test shared memory structure
void test_shared_memory_layout() {
    struct HidSharedMemory mem;
    assert(sizeof(mem.npad_entries[0][0]) == expected_size);
    // Verify offsets match Switch layout
}

// Test button mapping
void test_button_mapping() {
    uint64_t android_buttons = ANDROID_BUTTON_A;
    uint64_t switch_buttons = map_android_to_switch(android_buttons);
    assert(switch_buttons == SWITCH_BUTTON_B);
}

// Test axis conversion
void test_axis_conversion() {
    float android_value = 0.5f;
    int32_t switch_value = android_to_switch_axis(android_value);
    assert(switch_value == 16383); // 0.5 * 32767
}
```

### 7.2 Integration Testing

1. **Log guest HID calls**: Add logging to see what Diablo III actually requests
2. **Verify shared memory**: Dump memory contents after input to verify structure
3. **Test with USB controller**: Use physical controller on tablet
4. **Test touch overlay**: Virtual gamepad on touchscreen
5. **Monitor sampling rate**: Ensure input doesn't lag

### 7.3 Compatibility Testing

Test with various Android controllers:
- Xbox controllers (USB/Bluetooth)
- PlayStation controllers
- Generic HID controllers
- Touch overlays (virtual gamepad apps)

---

## 8. Performance Considerations

### 8.1 Latency Optimization

- **Polling rate**: 250Hz (4ms) for controller input
- **Sensor rate**: SENSOR_DELAY_GAME (50Hz typical)
- **Lock-free updates**: Use atomic writes to shared memory
- **JNI optimization**: Cache method IDs, minimize AttachCurrentThread calls

### 8.2 Memory

- Shared memory: ~256KB for all HID state
- Ring buffers prevent unbounded growth
- No dynamic allocation in hot path

### 8.3 CPU

- Input thread separate from render thread
- JNI calls batched where possible
- Sensor fusion done in Android (TYPE_GAME_ROTATION_VECTOR)

---

## 9. Future Enhancements

### 9.1 Advanced Features

- **Vibration/Haptics**: Map Switch vibration commands to Android Vibrator API
- **HD Rumble**: Convert linear actuator commands to Android amplitude/frequency
- **IR Camera**: Stubbed (Diablo III doesn't use)
- **NFC**: Stubbed (for amiibo support, not needed)

### 9.2 Input Remapping

- **Button remapping UI**: Let users customize layout
- **Multiple controller profiles**: Different layouts per game
- **Touch-to-button mapping**: Virtual gamepad overlay
- **Sensitivity/deadzone tuning**: Per-game settings

### 9.3 Multiplayer

- Support multiple physical controllers (up to 8 players)
- Handle controller connection/disconnection events
- Player LED patterns (if supported by controller)

---

## 10. Known Issues and Workarounds

### 10.1 Button Layout Differences

**Problem**: Xbox layout (Android default) has A/B and X/Y swapped vs Switch

**Solution**: Remap in software as shown in code skeleton

**User config**: Allow "Switch layout" vs "Xbox layout" preference

### 10.2 Analog Trigger Support

**Problem**: Switch has digital L/R + analog ZL/ZR, Xbox has analog triggers

**Solution**: Map Android L2/R2 (analog) to Switch ZL/ZR, use threshold for L/R buttons

### 10.3 Motion Control Orientation

**Problem**: Tablet held differently than Switch in handheld mode

**Solution**: Apply rotation matrix to convert Android sensor coordinates to Switch expected orientation

### 10.4 Touch vs Controller Priority

**Problem**: Both touch and controller active, which takes precedence?

**Solution**: Game mode setting - "Controller primary" disables touch gamepad, "Touch primary" for menu navigation

---

## 11. Resources and References

### Documentation
- **Switch Homebrew**: switchbrew.org/wiki/HID_services
- **Android Input**: developer.android.com/develop/ui/views/touch-and-input
- **SDL2 GameController**: wiki.libsdl.org/CategoryGameController

### Source Code (for reference only, licensing varies)
- **Yuzu**: github.com/yuzu-emu/yuzu (GPL-2.0)
- **Ryujinx**: github.com/Ryujinx/Ryujinx (MIT)
- **SDL2**: github.com/libsdl-org/SDL (Zlib)

### Tools
- **Controller tester apps**: Android apps to test controller input
- **adb input**: `adb shell input` for automated testing
- **logcat filtering**: Monitor input events

---

## 12. Next Steps for Implementation

### Phase 1: Minimal Boot Support (Est: 40-80 hours)
1. Implement basic HID service structure
2. Stub critical commands (ActivateNpad, SetSupportedNpadStyleSet)
3. Allocate shared memory
4. Verify game boots past HID initialization

### Phase 2: Basic Input (Est: 80-120 hours)
1. Implement JNI bridge to Android GameController
2. Button mapping (digital inputs)
3. Analog stick support
4. Update shared memory with real input
5. Test basic movement in game

### Phase 3: Full Input (Est: 60-100 hours)
1. Touch screen support
2. Six-axis sensor support
3. Event handles for input notifications
4. Multi-controller support
5. Vibration output

### Phase 4: Polish (Est: 40-60 hours)
1. Input remapping UI
2. Performance tuning
3. Compatibility testing
4. User preferences/settings
5. Documentation

**Total estimate**: 220-360 hours for complete HID implementation

---

**Document Status**: Research complete, ready for implementation planning
**Last Updated**: 2026-10-16
**Related**: ROADMAP.md Stage 3, d3-android/GOAL.md
