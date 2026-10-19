    .text
    .p2align 4
    .global d3_test_guest_roundtrip
    .type d3_test_guest_roundtrip, %function
d3_test_guest_roundtrip:
    stp x19, x20, [sp, #-48]!
    stp x21, x22, [sp, #16]
    stp x29, x30, [sp, #32]
    mov x29, sp
    mov x22, x0
    mov x19, x1
    mrs x20, tpidr_el0
    mov x21, x18
    mov x18, x20
    dup v16.2d, x20
    dup v31.2d, x20
    ldr x0, [x19, #32]
    blr x22
    str x0, [x19]
    str x20, [x19, #8]
    mrs x22, tpidr_el0
    str x22, [x19, #16]
    str x18, [x19, #24]
    stp q16, q31, [x19, #48]
    mov x18, x21
    ldp x29, x30, [sp, #32]
    ldp x21, x22, [sp, #16]
    ldp x19, x20, [sp], #48
    ret
    .size d3_test_guest_roundtrip, . - d3_test_guest_roundtrip

    .p2align 4
    .global d3_test_guest_counter
    .type d3_test_guest_counter, %function
d3_test_guest_counter:
    mrs x0, cntpct_el0
    ret
    .size d3_test_guest_counter, . - d3_test_guest_counter

    .p2align 4
    .global d3_test_guest_vibration
    .type d3_test_guest_vibration, %function
d3_test_guest_vibration:
    mov x9, x0
    ldr x16, [x9]
    ldr x0, [x9, #8]
    ldr x1, [x9, #16]
    ldr w2, [x9, #24]
    ldr w3, [x9, #28]
    ldr w4, [x9, #32]
    br x16
    .size d3_test_guest_vibration, . - d3_test_guest_vibration
