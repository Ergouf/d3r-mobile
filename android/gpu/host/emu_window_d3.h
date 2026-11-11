// Minimal EmuWindow for the d3 Android shell.
//
// Eden's renderer only needs two things from the frontend: a window system
// description that names the native surface, and a graphics context factory.
// Both are trivial here because the whole host is a single-process Android app.
#pragma once

#include <android/native_window.h>

#include <memory>
#include <atomic>
#include <vector>

#include "core/frontend/emu_window.h"
#include "core/frontend/graphics_context.h"
#include "video_core/vulkan_common/vulkan_library.h"

namespace D3 {

std::shared_ptr<Common::DynamicLibrary> OpenDriverLibrary();

/// Graphics context handed to the renderer.  The driver library is the same
/// libvulkan the rest of the host loads, so no per-thread state is needed.
class GraphicsContextD3 final : public Core::Frontend::GraphicsContext {
public:
    std::shared_ptr<Common::DynamicLibrary> GetDriverLibrary() override {
        return OpenDriverLibrary();
    }
};

class EmuWindowD3 final : public Core::Frontend::EmuWindow {
public:
    explicit EmuWindowD3(ANativeWindow* window);
    ~EmuWindowD3() override;
    void SetSurface(ANativeWindow* window);

    std::unique_ptr<Core::Frontend::GraphicsContext> CreateSharedContext() const override;

    bool IsShown() const override {
        return shown.load(std::memory_order_acquire);
    }

    ANativeWindow* Surface() const {
        return surface;
    }

private:
    ANativeWindow* surface{};
    std::atomic_bool shown{};
    std::vector<ANativeWindow*> retained_surfaces;
};

} // namespace D3
