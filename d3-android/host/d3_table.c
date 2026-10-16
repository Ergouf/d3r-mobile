// d3_table.c - Host-guest shared data table initialization

#include <stdint.h>
#include <string.h>
#include "guest_layout.h"

// Shared table between host and guest
// Size should be adequate for all shared data
#define D3_TABLE_SIZE 1024

uint64_t g_table[D3_TABLE_SIZE];

// Initialize the shared table
void d3_table_init(uint64_t tlr_base) {
    memset(g_table, 0, sizeof(g_table));

    // Store TLR base address
    g_table[D3_HOST_OFF_TLR / 8] = tlr_base;

    // Initialize crash counters
    g_table[D3_HOST_OFF_CRASH_COUNT / 8] = 0;
    g_table[D3_HOST_OFF_LAST_CRASH_PC / 8] = 0;
}

// Get TLR from table
uint64_t d3_get_tlr(void) {
    return g_table[D3_HOST_OFF_TLR / 8];
}

// Set TLR in table
void d3_set_tlr(uint64_t tlr) {
    g_table[D3_HOST_OFF_TLR / 8] = tlr;
}
