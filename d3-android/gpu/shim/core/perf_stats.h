#pragma once
// Minimal perf counters: video_core only signals frame boundaries.
namespace Core {

class PerfStats {
public:
    PerfStats() = default;

    void EndSystemFrame();
    void EndGameFrame();
};

} // namespace Core
