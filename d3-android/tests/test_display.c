#include "../host/d3_display.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    const uint32_t original[6] = {0xd280c808, 0xd280a009, 0xf2c07088, 0xf2c05a09, 0x5291c72a, 0x72a7fc6a};
    uint32_t code[6];
    uint32_t letterbox_aspect = 0x3fe38e39;
    memcpy(code, original, sizeof code);
    assert(d3_display_patch(code, &letterbox_aspect, 2000, 900) == 0);
    assert(((code[0] >> 5) & 0xffff) == 2000);
    assert(((code[1] >> 5) & 0xffff) == 1600);
    assert(((code[2] >> 5) & 0xffff) == 900);
    assert(((code[3] >> 5) & 0xffff) == 720);
    uint32_t bits = ((code[4] >> 5) & 0xffff) | ((code[5] >> 5) & 0xffff) << 16;
    float aspect;
    memcpy(&aspect, &bits, sizeof aspect);
    assert(aspect > 2.222f && aspect < 2.223f);
    assert(letterbox_aspect == bits);
    assert(d3_display_patch(code, &letterbox_aspect, 2000, 900) == -1);
    memcpy(code, original, sizeof code);
    letterbox_aspect = 0;
    assert(d3_display_patch(code, &letterbox_aspect, 2000, 900) == -1);
    assert(!memcmp(code, original, sizeof code));
    assert(letterbox_aspect == 0);
    letterbox_aspect = 0x3fe38e39;
    assert(d3_display_patch(code, &letterbox_aspect, 8000, 900) == -1);
    assert(!memcmp(code, original, sizeof code));
    assert(d3_display_patch(code, &letterbox_aspect, 2000, 1080) == -1);
    assert(!memcmp(code, original, sizeof code));
    assert(d3_display_patch(code, &letterbox_aspect, 1599, 900) == -1);
    assert(!memcmp(code, original, sizeof code));
    assert(d3_display_patch(code, &letterbox_aspect, 1600, 900) == 0);
    assert(!memcmp(code, original, sizeof code));
    assert(d3_display_patch(code, &letterbox_aspect, 4096, 900) == 0);
    assert(((code[0] >> 5) & 0xffff) == 4096);
    for (size_t index = 0; index < 6; ++index) {
        memcpy(code, original, sizeof code);
        letterbox_aspect = 0x3fe38e39;
        code[index] ^= 1;
        uint32_t mismatched[6];
        memcpy(mismatched, code, sizeof code);
        assert(d3_display_patch(code, &letterbox_aspect, 2000, 900) == -1);
        assert(!memcmp(code, mismatched, sizeof code));
        assert(letterbox_aspect == 0x3fe38e39);
    }
    puts("Verified guest-resolution patch, aspect and mismatch guards passed");
    return 0;
}
