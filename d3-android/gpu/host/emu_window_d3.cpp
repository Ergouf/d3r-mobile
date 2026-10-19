#include "emu_window_d3.h"

namespace D3 {

EmuWindowD3::EmuWindowD3(ANativeWindow* window) {
    SetSurface(window);
}

EmuWindowD3::~EmuWindowD3() {
    for (auto* window : retained_surfaces) ANativeWindow_release(window);
}

void EmuWindowD3::SetSurface(ANativeWindow* window) {
    if (window && window != surface) {
        ANativeWindow_acquire(window);
        retained_surfaces.push_back(window);
    }
    surface = window;
    window_info.type = Core::Frontend::WindowSystemType::Android;
    window_info.render_surface = window;
    window_info.render_surface_scale = 1.0f;

    if (window) {
        UpdateCurrentFramebufferLayout(static_cast<u32>(ANativeWindow_getWidth(window)),
                                       static_cast<u32>(ANativeWindow_getHeight(window)));
    }
    shown.store(window != nullptr, std::memory_order_release);
}

std::unique_ptr<Core::Frontend::GraphicsContext> EmuWindowD3::CreateSharedContext() const {
    return std::make_unique<GraphicsContextD3>();
}

} // namespace D3
