#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>

namespace D3 {
struct SceneRegion {
    std::array<int, 4> output; // x, y, width, height in physical framebuffer pixels
    std::array<float, 4> crop; // normalized left, top, right, bottom
    std::array<int, 4> source; // left, top, right, bottom in physical source pixels
};

inline std::optional<SceneRegion> MakeSceneRegion(
    const std::array<float, 4>& remap, const std::array<float, 4>& viewport,
    const std::array<std::int64_t, 4>& scissor,
    const std::array<std::uint32_t, 2>& input, const std::array<std::uint32_t, 2>& framebuffer) {
    for (float x : remap) if (!std::isfinite(x)) return {};
    if (remap[1] < 0 || remap[3] < 0 || remap[0] <= 0 || remap[2] <= 0 ||
        remap[1] + remap[0] > 1.00001f || remap[3] + remap[2] > 1.00001f) return {};
    // The identified D3 compositor uses a negative-height Vulkan viewport.
    if (viewport[2] <= 0 || viewport[3] >= 0) return {};
    const std::array<float, 4> rect{viewport[0], viewport[1] + viewport[3], viewport[2], -viewport[3]};
    SceneRegion region{};
    auto& out = region.output;
    for (std::size_t n = 0; n < rect.size(); ++n) {
        if (!std::isfinite(rect[n]) || rect[n] < 0 || rect[n] > 32768) return {};
        out[n] = std::lround(rect[n]);
        if (std::abs(rect[n] - out[n]) > 0.01f) return {};
    }
    if (!out[2] || !out[3] || std::uint32_t(out[0] + out[2]) > framebuffer[0] ||
        std::uint32_t(out[1] + out[3]) > framebuffer[1] ||
        scissor[0] > out[0] || scissor[1] > out[1] ||
        scissor[0] + scissor[2] < out[0] + out[2] || scissor[1] + scissor[3] < out[1] + out[3] ||
        !input[0] || !input[1] || input[0] * remap[0] > out[2] || input[1] * remap[2] > out[3]) return {};
    region.crop = {remap[1], remap[3], remap[1] + remap[0], remap[3] + remap[2]};
    for (std::size_t n = 0; n < region.source.size(); ++n)
        region.source[n] = std::lround(region.crop[n] * input[n % 2]);
    if (region.source[2] <= region.source[0] || region.source[3] <= region.source[1]) return {};
    return region;
}
}
