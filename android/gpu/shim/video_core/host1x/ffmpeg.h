#pragma once
// Video decoding (NVDEC + FFmpeg) is out of scope for the first frame.  Eden's
// host1x headers still name a few decoder types, so those are declared here and
// the files that actually decode video are excluded from the build.
#include <memory>

namespace FFmpeg {

struct Frame;

struct FrameDimensions {
    u32 width{};
    u32 height{};
};

class DecodeApi {
public:
    [[nodiscard]] bool UsingDecodeOrder() const { return false; }
};

class Decoder {
public:
    Decoder() = default;
    virtual ~Decoder() = default;
};

} // namespace FFmpeg
