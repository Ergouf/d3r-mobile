#pragma once
// Guest address space.  Eden's GuestMemory templates and the device page-table
// code call into this backend; only members that the GPU port actually reaches
// are declared here until the host binds them to the real guest mappings.
#include <cstddef>
#include <span>

#include "common/common_types.h"
#include "common/typed_address.h"
#include "core/guest_memory.h"

namespace Core::Memory {

inline constexpr std::size_t YUZU_PAGEBITS = 12;
inline constexpr u64 YUZU_PAGESIZE = u64{1} << YUZU_PAGEBITS;
inline constexpr u64 YUZU_PAGEMASK = YUZU_PAGESIZE - 1;

class Memory {
public:
    Memory() = default;

    // The port performs explicit flushes around GPU work; guest memory here is
    // ordinary mapped RAM, so GuestMemory skips its invalidation hooks.
    static constexpr bool HAS_FLUSH_INVALIDATION = false;

    void FlushRegion(u64 addr, std::size_t size);
    void InvalidateRegion(u64 addr, std::size_t size);

    u8* GetSpan(u64 addr, std::size_t size);
    [[nodiscard]] const u8* GetSpan(u64 addr, std::size_t size) const;

    u8* GetPointer(Common::ProcessAddress vaddr);
    u8* GetPointerSilent(Common::ProcessAddress vaddr);
    [[nodiscard]] const u8* GetPointer(Common::ProcessAddress vaddr) const;

    template <typename T>
    T* GetPointer(Common::ProcessAddress vaddr) {
        return reinterpret_cast<T*>(GetPointer(vaddr));
    }

    template <typename T>
    const T* GetPointer(Common::ProcessAddress vaddr) const {
        return reinterpret_cast<const T*>(GetPointer(vaddr));
    }

    void ReadBlock(u64 src, void* dest, std::size_t size) const;
    void ReadBlockUnsafe(u64 src, void* dest, std::size_t size) const;
    void WriteBlock(u64 dest, const void* src, std::size_t size);
    void WriteBlockCached(u64 dest, const void* src, std::size_t size);
    void WriteBlockUnsafe(u64 dest, const void* src, std::size_t size);

    void RasterizerMarkRegionCached(Common::ProcessAddress vaddr, u64 size, bool cached);
};

template <typename T, GuestMemoryFlags FLAGS>
using CpuGuestMemory = GuestMemory<Core::Memory::Memory, T, FLAGS>;

} // namespace Core::Memory
