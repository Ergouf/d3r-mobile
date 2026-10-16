/* Reconstructed from the preserved guest ELF, host disassembly, and header fragment. */
#ifndef D3_GUEST_LAYOUT_H
#define D3_GUEST_LAYOUT_H

#include <stdint.h>

#define D3_SDK_BASE       0x00010000u
#define D3_MAIN_BASE      0x01000000u
#define D3_VENEER_BASE    0x03000000u
#define D3_NAME_BASE      0x03080000u
#define D3_HOST_TABLE     0x03100000u
#define D3_SDK_TEXT_END   0x00550950u
#define D3_MAIN_TEXT_END  0x01c72b90u

#define D3_HOST_OFF_DISPATCH  0u
#define D3_HOST_OFF_HOST_TP   8u
#define D3_HOST_OFF_GUEST_TP 16u
#define D3_HOST_OFF_TLR      24u
#define D3_HOST_OFF_MAGIC    32u
#define D3_HOST_MAGIC       UINT64_C(0x54534f483344)

enum {
    D3_KIND_SVC = 1,
    D3_KIND_TPIDRRO = 2,
    D3_KIND_CALL = 3,
    D3_KIND_SYSTEM_TICK = 4
};
#define D3_CALL_EXCEPTION_STACK 1u

#define D3_SYM__init_libc0               0x004dbcd8u
#define D3_SYM_nnosInitialize            0x00349af0u
#define D3_SYM__init_libc1               0x004dbce0u
#define D3_SYM_nninitInitializeSdkModule 0x002ad960u
#define D3_SYM_nninitStartup             0x01000a20u
#define D3_SYM__init_libc2               0x004dbce8u
#define D3_SYM_SetHostArgc               0x0033e090u
#define D3_SYM_SetHostArgv               0x0033e0b0u
#define D3_SYM_nnMain                    0x01000480u
#define D3_SDK_DT_INIT                   0x00010030u
#define D3_SDK_INIT_ARRAY                0x00c4bc88u
#define D3_SDK_INIT_ARRAYSZ              0x00000358u
#define D3_MAIN_DT_INIT                  0x01000030u
#define D3_MAIN_INIT_ARRAY               0x0215bed0u
#define D3_MAIN_INIT_ARRAYSZ             0x00000b40u

typedef struct d3_saved {
    uint64_t x[31];
    uint64_t nzcv;
    unsigned char q[8][16];
} d3_saved;

#endif
