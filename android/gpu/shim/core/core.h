#pragma once
// Shadow of Eden's core/core.h for the GPU port.  video_core only touches a
// handful of System members, so the kernel, services and Boost never enter the
// build.
#include <cstddef>
#include <cstdint>
#include <functional>

#include "common/common_types.h"
#include "core/core_timing.h"
#include "core/device_memory.h"
#include "core/memory.h"
#include "core/perf_stats.h"

namespace Tegra {
struct MaxwellDeviceTraits;
class GPU;
namespace Host1x {
class Host1x;
} // namespace Host1x
} // namespace Tegra

namespace Core {

class System {
public:
    System() = default;

    Tegra::GPU& GPU();
    Tegra::Host1x::Host1x& Host1x();
    CoreTiming& CoreTiming();
    Core::DeviceMemory& DeviceMemory();
    const Core::DeviceMemory& DeviceMemory() const;
    Core::Memory::Memory& ApplicationMemory();
    const Core::Memory::Memory& ApplicationMemory() const;

    [[nodiscard]] bool IsPoweredOn() const;

    void RegisterHostThread();

    void GatherGPUDirtyMemory(std::function<void(PAddr, std::size_t)>& callback);

    [[nodiscard]] Core::PerfStats& GetPerfStats();
    [[nodiscard]] const Core::PerfStats& GetPerfStats() const;
};

} // namespace Core
