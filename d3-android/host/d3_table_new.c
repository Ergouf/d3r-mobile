// d3_table.c - Host-guest shared data table initialization

#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "guest_layout.h"

// Shared table between host and guest
// Must be large enough for all shared data
#define D3_TABLE_SIZE 1024

uint64_t g_table[D3_TABLE_SIZE];

// Global state
uint64_t g_bias = 0;         // Base address of guest code
uint64_t g_guest_tid = 0;    // Guest thread ID
int g_loud = 5;              // Logging verbosity (0=quiet, 10=verbose)

// Initialize the shared table
void d3_table_init(uint64_t bias, uint64_t guest_tid) {
    memset(g_table, 0, sizeof(g_table));

    // Store global state
    g_bias = bias;
    g_guest_tid = guest_tid;

    printf("[d3_table] Initialized: bias=%#lx tid=%lu\n", bias, guest_tid);
}

// Set TLR (Thread-Local Region) base address
void d3_set_tlr(uint64_t tlr) {
    g_table[D3_HOST_OFF_TLR / 8] = tlr;
    printf("[d3_table] TLR set to %#lx\n", tlr);
}

// Get TLR from table
uint64_t d3_get_tlr(void) {
    return g_table[D3_HOST_OFF_TLR / 8];
}

// Increment crash counter (for loop detection)
void d3_increment_crash_count(void) {
    g_table[D3_HOST_OFF_CRASH_COUNT / 8]++;
}

// Get crash counter
uint64_t d3_get_crash_count(void) {
    return g_table[D3_HOST_OFF_CRASH_COUNT / 8];
}

// Reset crash counter
void d3_reset_crash_count(void) {
    g_table[D3_HOST_OFF_CRASH_COUNT / 8] = 0;
}

// Set last crash PC (for loop detection)
void d3_set_last_crash_pc(uint64_t pc) {
    g_table[D3_HOST_OFF_LAST_CRASH_PC / 8] = pc;
}

// Get last crash PC
uint64_t d3_get_last_crash_pc(void) {
    return g_table[D3_HOST_OFF_LAST_CRASH_PC / 8];
}

// Print table status for debugging
void d3_table_dump(void) {
    printf("[d3_table] Status:\n");
    printf("  g_bias = %#lx\n", g_bias);
    printf("  g_guest_tid = %lu\n", g_guest_tid);
    printf("  g_loud = %d\n", g_loud);
    printf("  TLR = %#lx\n", d3_get_tlr());
    printf("  crash_count = %lu\n", d3_get_crash_count());
    printf("  last_crash_pc = %#lx\n", d3_get_last_crash_pc());
}
