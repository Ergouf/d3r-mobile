#pragma once
// The GPU port does not model Eden's kernel page tables; the GPU page table in
// video_core/memory_manager.cpp is self-contained.
namespace Kernel {
class KPageTable;
}
