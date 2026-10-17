// guest_layout.h - Memory layout definitions and shared structures
#ifndef D3_GUEST_LAYOUT_H
#define D3_GUEST_LAYOUT_H

#include <stdint.h>
#include <signal.h>
#include <sys/ucontext.h>
#include <stdlib.h>

// Host-guest shared table offsets (in bytes)
#define D3_HOST_OFF_TLR           24    // Thread-Local Region base pointer
#define D3_HOST_OFF_CRASH_COUNT   32    // Crash counter for loop detection
#define D3_HOST_OFF_LAST_CRASH_PC 40    // Last crash PC for detection

// Memory regions
#define D3_CRASH_REGION_START 0x371400  // Start of logging crash region
#define D3_CRASH_REGION_END   0x371900  // End of logging crash region

// Saved register context structure
typedef struct {
    uint64_t x[31];     // x0-x30 (x30 is LR/link register)
    uint64_t pc;        // Program counter (saved as x[30] in some contexts)
    uint64_t pstate;    // Processor state
} d3_saved;

// Global variables (defined in d3_table.c)
extern uint64_t g_table[];
extern uint64_t g_bias;
extern uint64_t g_guest_tid;
extern int g_loud;

// d3_table.c functions
void d3_table_init(uint64_t bias, uint64_t guest_tid);
void d3_set_tlr(uint64_t tlr);
uint64_t d3_get_tlr(void);
void d3_increment_crash_count(void);
uint64_t d3_get_crash_count(void);
void d3_reset_crash_count(void);
void d3_set_last_crash_pc(uint64_t pc);
uint64_t d3_get_last_crash_pc(void);
void d3_table_dump(void);

// d3_host.c functions
int safe_read(uint64_t addr, void *buf, size_t size);
void set_saved(d3_saved *saved, uint32_t reg, uint64_t value);
void on_tpidrro(d3_saved *saved, uint64_t reg_num);
void handle_break_0x26(d3_saved *saved);
int d3_hle_dispatch(d3_saved *saved, int kind, uint64_t extra);

// Logging macros
/* Guest threads are real threads now, so every line carries the host tid to
   make interleaved logs attributable. */
long d3_host_tid(void);

#define info(fmt, ...) \
    do { if (g_loud > 0) printf("[D3Host t%ld] " fmt "\n", d3_host_tid(), ##__VA_ARGS__); } while(0)

#define slog(fmt, ...) \
    do { if (g_loud > 0) printf("[D3Host t%ld] " fmt "\n", d3_host_tid(), ##__VA_ARGS__); } while(0)

#define fail(fmt, ...) \
    do { \
        printf("[D3Host ERROR] " fmt "\n", ##__VA_ARGS__); \
        _exit(1); \
    } while(0)

#endif // D3_GUEST_LAYOUT_H
