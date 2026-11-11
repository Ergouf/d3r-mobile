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
    const uint32_t original_calls[2] = {0x9402e0d7, 0x9402df8e};
    uint32_t camera_calls[2];
    memcpy(camera_calls, original_calls, sizeof camera_calls);
    uint32_t camera_padding[4] = {0xd65f03c0, 0, 0, 0};
    float scale;
    assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 2000, &scale) == 0);
    assert(scale == 0.78125f);
    assert(camera_padding[1] == 0x1e2d3000);
    assert(camera_padding[2] == 0x1e200940);
    /* The stable submission returns before reaching the transition call. */
    assert(0x11ad364 + (camera_calls[0] & 0x03ffffff) * 4 == 0x129b4c4);
    assert(0x11ad888 + (camera_calls[1] & 0x03ffffff) * 4 == 0x129b4c4);
    assert(0x129b4cc + ((int32_t)(camera_padding[3] << 6) >> 6) * 4 == 0x12656c0);
    uint32_t patched_calls[2], patched_padding[4];
    memcpy(patched_calls, camera_calls, sizeof camera_calls);
    memcpy(patched_padding, camera_padding, sizeof camera_padding);
    assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 2000, &scale) == -1);
    assert(!memcmp(camera_calls, patched_calls, sizeof camera_calls));
    assert(!memcmp(camera_padding, patched_padding, sizeof camera_padding));
    assert(scale == 0.78125f);
    /* Reject either previously patched call even with fresh trampoline space. */
    for (size_t index = 0; index < 2; ++index) {
        memcpy(camera_calls, original_calls, sizeof camera_calls);
        camera_calls[index] = patched_calls[index];
        camera_padding[1] = camera_padding[2] = camera_padding[3] = 0;
        uint32_t before[2];
        memcpy(before, camera_calls, sizeof before);
        assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 2000, &scale) == -1);
        assert(!memcmp(camera_calls, before, sizeof before));
        assert(camera_padding[1] == 0 && camera_padding[2] == 0 && camera_padding[3] == 0);
    }
    memcpy(camera_calls, original_calls, sizeof camera_calls);
    camera_padding[1] = camera_padding[2] = camera_padding[3] = 0;
    assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 4096, &scale) == 0);
    assert(scale <= 1600.0f / 4096 && scale > 0);
    /* Every call, return and padding guard must reject without partial writes. */
    for (size_t index = 0; index < 6; ++index) {
        memcpy(camera_calls, original_calls, sizeof camera_calls);
        camera_padding[0] = 0xd65f03c0;
        camera_padding[1] = camera_padding[2] = camera_padding[3] = 0;
        if (index < 2) camera_calls[index] ^= 1;
        else camera_padding[index - 2] ^= 1;
        uint32_t before_calls[2], before_padding[4];
        memcpy(before_calls, camera_calls, sizeof before_calls);
        memcpy(before_padding, camera_padding, sizeof before_padding);
        scale = -1;
        assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 2000, &scale) == -1);
        assert(!memcmp(camera_calls, before_calls, sizeof before_calls));
        assert(!memcmp(camera_padding, before_padding, sizeof before_padding));
        assert(scale == -1);
    }
    memcpy(camera_calls, original_calls, sizeof camera_calls);
    camera_padding[0] = 0xd65f03c0;
    camera_padding[1] = camera_padding[2] = camera_padding[3] = 0;
    assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 5000, &scale) == -1);
    assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 1599, &scale) == -1);
    assert(!memcmp(camera_calls, original_calls, sizeof camera_calls));
    assert(camera_padding[1] == 0 && camera_padding[2] == 0 && camera_padding[3] == 0);
    assert(d3_display_menu_patch(camera_calls, camera_calls + 1, camera_padding + 1, 1600, &scale) == 0);
    assert(scale == 1.0f);
    puts("Verified guest-resolution patch, stable/transition menu FOV and mismatch guards passed");
    return 0;
}
