    .text
    .p2align 4
    .global d3_test_hud_frame
    .type d3_test_hud_frame, %function
d3_test_hud_frame:
    str d10, [sp, #-0x80]!
    stp d9, d8, [sp, #0x10]
    stp x28, x27, [sp, #0x20]
    stp x26, x25, [sp, #0x30]
    stp x24, x23, [sp, #0x40]
    stp x22, x21, [sp, #0x50]
    stp x20, x19, [sp, #0x60]
    stp x29, x30, [sp, #0x70]
    add x29, sp, #0x70
    sub sp, sp, #0x2a0
    b d3_hud_frame_bridge
    .global d3_test_hud_frame_resume
d3_test_hud_frame_resume:
    ldp x24, x23, [sp, #0x40]
    ldp x26, x25, [sp, #0x30]
    ldp x28, x27, [sp, #0x20]
    ldr d10, [sp], #0x80
    ret
    .size d3_test_hud_frame, . - d3_test_hud_frame

    .p2align 4
    .global d3_test_invoke_hud_frame
    .type d3_test_invoke_hud_frame, %function
d3_test_invoke_hud_frame:
    stp x19, x20, [sp, #-48]!
    stp x21, x30, [sp, #16]
    str x18, [sp, #32]
    mrs x19, tpidr_el0
    mov x20, x1
    mov x21, x2
    msr tpidr_el0, x0
    mov x18, x20
    mov x0, #0x1234
    mov x1, #0x5678
    bl d3_test_hud_frame
    stp x0, x1, [x21]
    mrs x9, tpidr_el0
    stp x9, x18, [x21, #16]
    msr tpidr_el0, x19
    ldr x18, [sp, #32]
    ldp x21, x30, [sp, #16]
    ldp x19, x20, [sp], #48
    ret
    .size d3_test_invoke_hud_frame, . - d3_test_invoke_hud_frame
