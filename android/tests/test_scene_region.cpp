#include "scene_region.h"
#include "scene_policy.h"
#include <cassert>
#include <iostream>
#include <limits>

int main() {
    for (int mode : {D3::SceneFsrMode, D3::SceneFourFifthsMode, D3::SceneFiveEighthMode, D3::SceneSevenEighthMode}) {
        assert(D3::IsSceneMode(mode));
        const auto width = (1600 * D3::SceneScaleNumerator(mode)) >> D3::SceneScaleShift(mode);
        const auto height = (720 * D3::SceneScaleNumerator(mode)) >> D3::SceneScaleShift(mode);
        auto scaled = D3::MakeSceneRegion({1, 0, 1, 0}, {0, 720, 1600, -720},
            {0, 0, 2000, 900}, {width, height}, {2000, 900});
        assert(scaled && scaled->source[2] == static_cast<int>(width) &&
               scaled->source[3] == static_cast<int>(height));
    }
    assert((1600 * D3::SceneScaleNumerator(D3::SceneFourFifthsMode) >> D3::SceneScaleShift(D3::SceneFourFifthsMode)) == 1280);
    assert((720 * D3::SceneScaleNumerator(D3::SceneFourFifthsMode) >> D3::SceneScaleShift(D3::SceneFourFifthsMode)) == 576);
    assert(!D3::IsSceneMode(10));
    const std::array<float, 4> full{1, 0, 1, 0};
    const std::array<float, 4> viewport{0, 720, 1280, -720};
    const std::array<std::int64_t, 4> scissor{0, 0, 1600, 900};
    const std::array<std::uint32_t, 2> input{960, 540}, framebuffer{1600, 900};
    auto region = D3::MakeSceneRegion(full, viewport, scissor, input, framebuffer);
    assert(region && (region->output == std::array<int, 4>{0, 0, 1280, 720}));
    assert((region->crop == std::array<float, 4>{0, 0, 1, 1}));
    assert((region->source == std::array<int, 4>{0, 0, 960, 540}));
    // Logical 1600x720 scene views allocate a 1200x540 image at 0.75x.
    region = D3::MakeSceneRegion(full, {0, 720, 1600, -720}, {0, 0, 2000, 900},
                                 {1200, 540}, {2000, 900});
    assert(region && (region->source == std::array<int, 4>{0, 0, 1200, 540}));
    // Captured D3 dynamic-resolution case: 912x513 active pixels in a 960x540 image.
    region = D3::MakeSceneRegion({.95f, 0, .95f, 0}, viewport, scissor, input, framebuffer);
    assert(region && region->crop[2] == .95f && region->crop[3] == .95f);
    assert(region->output[2] == 1280 && region->output[3] == 720);
    assert((region->source == std::array<int, 4>{0, 0, 912, 513}));
    // A letterboxed viewport must not be stretched to the entire UI allocation.
    region = D3::MakeSceneRegion({.7f, .1f, .6f, .2f}, {80, 760, 1280, -720}, scissor, input, framebuffer);
    assert(region && (region->output == std::array<int, 4>{80, 40, 1280, 720}));
    assert(std::abs(region->crop[2] - .8f) < 1e-6f && region->crop[1] == .2f);
    assert((region->source == std::array<int, 4>{96, 108, 768, 432}));
    assert(!D3::MakeSceneRegion({.0001f, 0, .0001f, 0}, viewport, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion(full, viewport, {0, 0, 1000, 900}, input, framebuffer));
    assert(!D3::MakeSceneRegion(full, {0, 720, 1280, -720}, scissor, input, {1000, 900}));
    assert(!D3::MakeSceneRegion(full, {0, 720, 1280, 720}, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion(full, {.5f, 720, 1280, -720}, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion({1, .1f, 1, 0}, viewport, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion({1, -.1f, 1, 0}, viewport, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion({0, 0, 1, 0}, viewport, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion({std::numeric_limits<float>::quiet_NaN(), 0, 1, 0}, viewport, scissor, input, framebuffer));
    assert(!D3::MakeSceneRegion(full, viewport, scissor, {0, 540}, framebuffer));
    assert(!D3::MakeSceneRegion(full, viewport, scissor, {1920, 1080}, framebuffer));
    assert(D3::IsSceneCompositor(D3::SceneVertexHash, D3::SceneFragmentHash));
    assert(D3::IsSceneCompositor(D3::SceneVertexExitHash, D3::SceneFragmentExitHash));
    assert(!D3::IsSceneCompositor(D3::SceneVertexHash, D3::SceneFragmentExitHash));
    assert(!D3::IsSceneCompositor(0, D3::SceneFragmentHash));
    std::cout << "Scene crop, viewport, scissor and compositor gates passed\n";
}
