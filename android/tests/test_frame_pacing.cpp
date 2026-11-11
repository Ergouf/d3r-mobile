#include "frame_pacing.h"
#include <cassert>
#include <chrono>
#include <iostream>

int main() {
    using namespace std::chrono;
    const D3::FramePacer::Clock::time_point start{};
    D3::FramePacer pacer;
    assert(pacer.Deadline(start, 60) == start);
    auto deadline = pacer.Deadline(start + milliseconds(1), 60);
    assert(duration_cast<nanoseconds>(deadline - start).count() == 1'000'000'000 / 60);
    // GPU work exceeding a period cannot cause an immediate catch-up frame burst.
    assert(pacer.Deadline(start + milliseconds(100), 60) == start + milliseconds(100));
    deadline = pacer.Deadline(start + milliseconds(101), 60);
    assert(deadline > start + milliseconds(116));
    // Changing the requested cap starts a fresh schedule.
    assert(pacer.Deadline(start + milliseconds(120), 45) == start + milliseconds(120));
    deadline = pacer.Deadline(start + milliseconds(121), 45);
    assert(duration_cast<nanoseconds>(deadline - start - milliseconds(120)).count() == 1'000'000'000 / 45);

    // Frames ready early stay on a regular 45 fps schedule; a missed deadline
    // reanchors it instead of scheduling a burst of closely spaced frames.
    D3::FramePacer stable;
    const auto period45 = nanoseconds(1'000'000'000 / 45);
    assert(stable.Deadline(start, 45) == start);
    for (int frame = 1; frame <= 900; ++frame) {
        const auto ready = start + (frame - 1) * period45 + milliseconds(1);
        assert(stable.Deadline(ready, 45) == start + frame * period45);
    }
    const auto late = start + 902 * period45;
    assert(stable.Deadline(late, 45) == late);
    assert(stable.Deadline(late + milliseconds(1), 45) == late + period45);
    for (int cap : {30, 36, 40, 45, 60}) assert(D3::IsSupportedFrameCap(cap));
    assert(!D3::IsSupportedFrameCap(0) && !D3::IsSupportedFrameCap(120));
    std::cout << "Frame cap deadlines, late frames and cap changes passed\n";
}
