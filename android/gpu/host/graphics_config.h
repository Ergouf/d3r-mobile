#pragma once
#include <memory>
#include "common/dynamic_library.h"

namespace D3 {
void ApplyGraphicsConfiguration();
std::shared_ptr<Common::DynamicLibrary> OpenDriverLibrary();
}
