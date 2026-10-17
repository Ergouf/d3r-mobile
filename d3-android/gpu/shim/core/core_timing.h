#pragma once
// video_core only asks CoreTiming for the GPU tick counter, so the whole event
// queue (and its Boost fibonacci_heap) stays out of the build.
#include "common/common_types.h"

namespace Core {

class CoreTiming {
public:
    [[nodiscard]] u64 GetGPUTicks();
};

} // namespace Core
