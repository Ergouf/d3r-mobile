# HID and Input Handling Research for D3 Android Compatibility Layer

**Date:** 2026-10-16  
**Context:** Phase 3 preparation - Mapping Switch controller input (hid service) to Android touch/gamepad input

## Current Project State

### Architecture
- **Not an emulator**: ARM64 native execution with compatibility layer
- Guest code runs natively; only system calls and graphics APIs need translation
- Current phase: Stage 1.2 (past nnMain, blocked at cmd20 GetSharedMemory)

### Existing Implementation
**Host source files** (d3-android/host/):
- `d3_host.c` (90KB) - Main host runtime, SVC handlers
- `d3_service.c` (54KB) - IPC service handlers
- `d3_service_names.h` - Service and command name mappings
- `d3_sync.c` (8KB) - Synchronization primitives
- `d3_jni.c` - JNI bridge to Java MainActivity

**Current service implementations** (from d3_service_names.h):
- 26 implemented services out of 218 guest requests
- IApplicationFunctions, ICommonStateGetter, ISelfController
- IWindowController, IAudioController, IDisplayController
- ITimeService, ITimeZoneService
- **HID service: NOT YET IMPLEMENTED**

**Java layer** (MainActivity.java):
- Minimal diagnostic shell
- No input handling beyond start button
- No MotionEvent or GameController API usage yet

## Input Architecture Requirements

### Switch HID Service Structure
The Switch HID service handles:
1. **Controller input**: Buttons, analog sticks, triggers
2. **Motion controls**: Gyroscope, accelerometer (6-axis IMU)
3. **Multiple controllers**: Up to 8 Joy-Cons/Pro Controllers
4. **Touch screen**: Multi-touch for handheld mode
5. **Vibration/Haptics**: HD Rumble support

### Service Interface Pattern
Based on existing service implementations in d3_service_names.h:
- Services accessed via IPC (CMIF protocol)
- Each service has an interface ID and command set
- Need to add `D3_IF_HID` entry to enum
- Implement command handlers following existing pattern

### Android Input Targets

#### 1. Touch Input (MotionEvent)
```java
// For games without physical controller
public boolean onTouchEvent(MotionEvent event) {
    // Map touch to virtual gamepad
    // Or direct touch for UI elements
}
```

#### 2. GameController API
```java
// For physical controllers (Bluetooth/USB)
public boolean onGenericMotionEvent(MotionEvent event) {
    InputDevice device = event.getDevice();
    // Map AXIS_X, AXIS_Y, AXIS_Z, AXIS_RZ, etc.
}

public boolean onKeyEvent(KeyEvent event) {
    // Map KEYCODE_BUTTON_A, KEYCODE_BUTTON_B, etc.
}
```

#### 3. Sensor Manager (Motion)
```java
SensorManager sensorManager;
Sensor gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
Sensor accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
```

## Key Design Decisions

### Latency Optimization
1. **Native input processing**: Handle input in C/C++, not Java
2. **Direct NDK access**: Use AInputQueue from native-activity
3. **Polling vs Events**: Consider game loop integration
4. **Buffer management**: Shared memory for input state

### Motion Control Handling
1. **Sensor fusion**: Combine gyro + accel for orientation
2. **Calibration**: Match Switch sensitivity/dead zones
3. **Coordinate system**: Switch uses different axes than Android
4. **Update rate**: Switch polls at 200Hz, Android sensors vary

### Multiple Controller Support
1. **Device mapping**: Track which Android device = which Switch controller
2. **Player assignment**: Map InputDevice.getId() to Switch player slots
3. **Hotplug**: Handle connect/disconnect events

## Implementation Phases

### Phase 3A: Basic Input Stub (Blocking removal)
**Goal**: Unblock boot sequence when HID service is requested
**Implementation**:
- Add HID service port to `port_kind()` in d3_service.c
- Add HID interface enum to d3_service_names.h
- Return stub responses for common HID commands
- Allow boot to progress past HID initialization

### Phase 3B: Single Controller Support
**Goal**: Basic gameplay with one controller
**Implementation**:
- Implement HID shared memory structure
- Map Android GameController events to Switch button state
- Handle basic button input (A/B/X/Y, D-pad, shoulders)
- Analog stick mapping with dead zones

### Phase 3C: Motion Controls
**Goal**: Gyro aiming and tilt controls
**Implementation**:
- Read Android gyroscope/accelerometer sensors
- Transform coordinate systems (Android → Switch)
- Calibration and sensitivity adjustment
- Motion state in HID shared memory

### Phase 3D: Multi-controller & Advanced
**Goal**: Full feature parity
**Implementation**:
- Support multiple paired controllers
- Touch screen input for UI
- Vibration/haptics (if hardware supports)
- Controller configuration/remapping

## Code Patterns from Existing Services

### Service Registration Pattern
```c
// From d3_service.c port_kind()
static int port_kind(const char *name) {
    if (strcmp(name, "sm:") == 0)
        return PORT_SM;
    if (strcmp(name, "time:u") == 0)
        return PORT_TIME;
    // Add:
    if (strcmp(name, "hid") == 0)
        return PORT_HID;
    return PORT_UNKNOWN;
}
```

### Command Handler Pattern
```c
// Follow pattern from handle_time_command()
static int handle_hid_command(uint32_t cmd, uint32_t request_id, 
                               const void *input, void *output) {
    switch (cmd) {
        case HID_CMD_CREATE_APPLET_RESOURCE:
            // Implementation
            return 0;
        case HID_CMD_GET_SHARED_MEMORY_HANDLE:
            // Implementation
            return 0;
        default:
            slog("HID cmd %u unimplemented", cmd);
            return D3_RESULT(203, 3); // Unimplemented
    }
}
```

## External References to Research

### Switch HID Documentation
1. Switchbrew wiki - HID services documentation
2. libnx - Official Nintendo SDK headers (hid.h)
3. Yuzu emulator - core/hle/service/hid/
4. Ryujinx - Ryujinx.HLE/HOS/Services/Hid/

### Android Input References
1. NDK input.h - AInputEvent, AInputQueue
2. GameController guide - developer.android.com
3. Sensor API - SensorManager, SensorEventListener
4. MotionEvent reference - touch and controller events

### Controller Mapping Libraries
1. SDL2 game controller database
2. Antimicro-X - controller to keyboard mapper
3. Input-remapper - Linux input device remapper

## Testing Strategy

### Phase 3A Testing
- Boot continues past HID service requests
- Stub responses don't cause crashes
- Log shows HID commands being called

### Phase 3B Testing
1. Connect Xbox/PlayStation/Switch Pro controller via Bluetooth
2. Press buttons, verify log shows state changes
3. Test analog sticks with dead zone
4. Verify input reaches game logic

### Phase 3C Testing
1. Enable device motion sensors
2. Tilt device, verify gyro/accel values update
3. Test coordinate transformation accuracy
4. Measure input latency (target <16ms)

### Integration Testing
1. Play through tutorial level
2. Test all button combinations
3. Verify motion aiming works
4. Check controller disconnect/reconnect

## Next Steps for Phase 3

When ready to implement (after Stage 2 graphics complete):

1. **Research HID protocol details**
   - Read Switchbrew HID services page
   - Extract command IDs from Yuzu/Ryujinx
   - Document shared memory layout

2. **Create HID stub service**
   - Add PORT_HID and D3_IF_HID enums
   - Implement basic command handlers
   - Return success for initialization

3. **JNI input bridge**
   - Add native methods to MainActivity.java
   - Forward onKeyEvent/onGenericMotionEvent to native
   - Or use NDK native-activity pattern

4. **Implement input state buffer**
   - Allocate shared memory for HID state
   - Map to guest address space
   - Update from Android events

5. **Test with real game**
   - Verify button presses control character
   - Tune dead zones and sensitivity
   - Optimize for latency

## File Paths for Implementation

**Add HID service registration**:
- `d3-android/host/d3_service.c` (port_kind, dispatch)
- `d3-android/host/d3_service_names.h` (enums, command tables)
- `d3-android/host/d3_service.h` (function declarations)

**Create new HID implementation** (when needed):
- `d3-android/host/d3_hid.c` (new file)
- `d3-android/host/d3_hid.h` (new file)

**Java input handling**:
- `d3-android/app/src/com/d3mobile/host/MainActivity.java`

**Native JNI bridge**:
- `d3-android/host/d3_jni.c` (add input methods)

## Priority Notes

- **Not blocking current stage**: HID is Phase 3, graphics (Stage 2) comes first
- **Stub approach valid**: Return success stubs to unblock boot if HID requests appear
- **Research before implement**: Study Yuzu/Ryujinx HID implementations thoroughly
- **Test incrementally**: Start with buttons only, add motion later
- **Consider device constraints**: Galaxy Tab S8 has motion sensors, most devices do
