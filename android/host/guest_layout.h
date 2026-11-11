// guest_layout.h - Memory layout definitions and shared structures
#ifndef D3_GUEST_LAYOUT_H
#define D3_GUEST_LAYOUT_H

#include <stdint.h>

// Host-guest shared table offsets (in bytes)
#define D3_HOST_OFF_TLR           24    // Thread-Local Region base pointer
#define D3_HOST_OFF_CRASH_COUNT   32    // Crash counter for loop detection
#define D3_HOST_OFF_LAST_CRASH_PC 40    // Last crash PC for detection

// Saved register context structure
typedef struct {
    uint64_t x[31];     // x0-x30 (x30 is LR)
    uint64_t pc;        // Program counter
    uint64_t pstate;    // Processor state
} d3_saved;

// Forward declarations
extern uint64_t g_table[];
extern uint64_t g_bias;
extern uint64_t g_guest_tid;

#endif // D3_GUEST_LAYOUT_H
