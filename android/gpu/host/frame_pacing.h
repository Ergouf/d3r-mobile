#pragma once
#include <algorithm>
#include <chrono>

namespace D3 {
inline bool IsSupportedFrameCap(int fps) {
    return fps == 30 || fps == 36 || fps == 40 || fps == 45 || fps == 60;
}

class FramePacer {
public:
    using Clock = std::chrono::steady_clock;
    Clock::time_point Deadline(Clock::time_point now, int fps) {
        if (!IsSupportedFrameCap(fps)) fps = 60;
        if (!initialized || fps != current_fps) {
            initialized = true;
            current_fps = fps;
            deadline = now;
            return now;
        }
        const auto period = std::chrono::duration_cast<Clock::duration>(
            std::chrono::nanoseconds(1'000'000'000 / fps));
        // A slow frame starts a new schedule instead of causing a catch-up burst.
        deadline = std::max(now, deadline + period);
        return deadline;
    }
private:
    bool initialized{};
    int current_fps{};
    Clock::time_point deadline{};
};
}
