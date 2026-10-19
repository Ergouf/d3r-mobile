#ifndef D3_DISPLAY_H
#define D3_DISPLAY_H

#include <stdint.h>
#include <string.h>

static inline int d3_display_patch(uint32_t* code, uint32_t* letterbox_aspect, uint32_t width, uint32_t height) {
    static const uint32_t expected[6] = {
        0xd280c808, 0xd280a009, 0xf2c07088, 0xf2c05a09, 0x5291c72a, 0x72a7fc6a
    };
    if (width < 1600 || width > 4096 || height != 900 || *letterbox_aspect != 0x3fe38e39 ||
        memcmp(code, expected, sizeof expected)) return -1;
    const uint32_t handheld_width = ((uint64_t)width * 720 / height + 7) & ~7u;
    float aspect = (float)width / height;
    uint32_t aspect_bits;
    memcpy(&aspect_bits, &aspect, sizeof aspect_bits);
    code[0] = 0xd2800008 | width << 5;
    code[1] = 0xd2800009 | handheld_width << 5;
    code[2] = 0xf2c00008 | height << 5;
    code[3] = 0xf2c00009 | 720 << 5;
    code[4] = 0x5280000a | (aspect_bits & 0xffff) << 5;
    code[5] = 0x72a0000a | (aspect_bits >> 16) << 5;
    *letterbox_aspect = aspect_bits;
    return 0;
}

#endif
