#ifndef D3_HUD_H
#define D3_HUD_H

#include <math.h>
#include <stdint.h>

/* These are the registry keys from the verified update, not process addresses. */
#define D3_HUD_MAP_KEY UINT64_C(8378740584410653193)
#define D3_HUD_MAP_PARENT_KEY UINT64_C(104948615964533920)
#define D3_HUD_PLAYER_KEY UINT64_C(1141802117418794037)
#define D3_HUD_GROUP_KEY UINT64_C(8579397833293906375)

typedef struct { float left, top, right, bottom; } D3HudRect;

static inline int d3_hud_delta(const D3HudRect *root, const D3HudRect *widget,
                               int map, float delta[2]) {
    if (!isfinite(root->left) || !isfinite(root->top) || !isfinite(root->right) ||
        !isfinite(root->bottom) || !isfinite(widget->left) || !isfinite(widget->top) ||
        !isfinite(widget->right) || !isfinite(widget->bottom) ||
        root->right - root->left < 600.0f || root->right - root->left > 4096.0f ||
        root->bottom - root->top < 600.0f || root->bottom - root->top > 1000.0f ||
        widget->right < widget->left || widget->bottom < widget->top) return 0;
    if (map) {
        delta[0] = root->left + 21.6f - widget->left;
        delta[1] = root->top - 1.6f - widget->top;
    } else {
        delta[0] = (root->left + root->right - widget->left - widget->right) * 0.5f;
        delta[1] = 0;
    }
    return isfinite(delta[0]) && isfinite(delta[1]) &&
           fabsf(delta[0]) < 5000.0f && fabsf(delta[1]) < 5000.0f;
}

#endif
