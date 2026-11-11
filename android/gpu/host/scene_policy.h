#pragma once
#include <cstdint>
namespace D3 {
// Distinct from the retired whole-frame 0.75x preference (7).
inline constexpr int SceneFsrMode = 75;
inline constexpr int SceneFourFifthsMode = 80;
inline constexpr int SceneFiveEighthMode = 625;
inline constexpr int SceneSevenEighthMode = 875;
inline bool IsSceneMode(int mode) {
    return mode == SceneFsrMode || mode == SceneFourFifthsMode ||
           mode == SceneFiveEighthMode || mode == SceneSevenEighthMode;
}
inline std::uint32_t SceneScaleNumerator(int mode) {
    // Eden represents scales as numerator / 2^shift. 3277/4096 is within
    // 0.0062% of 0.8 and yields 1280x576 for D3's 1600x720 scene.
    return mode == SceneFourFifthsMode ? 3277 : mode == SceneFiveEighthMode ? 5 :
           mode == SceneSevenEighthMode ? 7 : 3;
}
inline std::uint32_t SceneScaleShift(int mode) {
    return mode == SceneFourFifthsMode ? 12 : mode == SceneFsrMode ? 2 : 3;
}
inline constexpr std::uint64_t SceneVertexHash = 0x4fe29a41ceaf7de2ULL;
inline constexpr std::uint64_t SceneFragmentHash = 0x09346d588c3f3203ULL;
inline constexpr std::uint64_t SceneVertexExitHash = 0x61cf33b470b4a795ULL;
inline constexpr std::uint64_t SceneFragmentExitHash = 0x2598d00907e82dafULL;
inline bool IsSceneCompositor(std::uint64_t vs, std::uint64_t fs) {
    return (vs == SceneVertexHash && fs == SceneFragmentHash) ||
           (vs == SceneVertexExitHash && fs == SceneFragmentExitHash);
}
void ConfigureSceneMode(bool enabled, std::uint32_t guest_width);
bool SceneModeEnabled();
bool IsSceneTarget(std::uint32_t width, std::uint32_t height);
}
