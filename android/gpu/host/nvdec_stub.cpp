// NVDEC / VIC placeholders.
//
// host1x.cpp instantiates the decoder and video-image-composer objects even when
// the guest never decodes video.  Diablo III does not touch NVDEC, so their
// behaviour is stubbed here instead of pulling FFmpeg and the codec backends
// into the APK.  Revisit if a title ever needs video playback.
#include <cstdlib>
#include <jni.h>
#include <span> // decoder.h relies on its includers for std::span

#include "video_core/host1x/codecs/decoder.h"
#include "video_core/host1x/codecs/h264.h"
#include "video_core/host1x/codecs/vp8.h"
#include "video_core/host1x/codecs/vp9.h"
#include "video_core/host1x/vic.h"

#include "common/android/applets/software_keyboard.h"
#include "common/android/applets/web_browser.h"
#include "common/android/multiplayer/multiplayer.h"

namespace Tegra {

Decoder::Decoder(Host1x::Host1x& host1x_, s32 id_,
                 const Host1x::NvdecCommon::NvdecRegisters& regs_)
    : host1x{host1x_}, regs{regs_}, id{id_} {}

Decoder::~Decoder() = default;

void Decoder::Decode() {
    std::abort();
}

namespace Decoders {

H264::H264(Host1x::Host1x& host1x_, const Host1x::NvdecCommon::NvdecRegisters& regs_, s32 id_)
    : Decoder{host1x_, id_, regs_} {}

H264::~H264() = default;

std::span<const u8> H264::ComposeFrame() {
    return {};
}

std::tuple<u64, u64> H264::GetProgressiveOffsets() {
    return {};
}

std::tuple<u64, u64, u64, u64> H264::GetInterlacedOffsets() {
    return {};
}

bool H264::IsInterlaced() {
    return false;
}

VP8::VP8(Host1x::Host1x& host1x_, const Host1x::NvdecCommon::NvdecRegisters& regs_, s32 id_)
    : Decoder{host1x_, id_, regs_} {}

VP8::~VP8() = default;

std::span<const u8> VP8::ComposeFrame() {
    return {};
}

std::tuple<u64, u64> VP8::GetProgressiveOffsets() {
    return {};
}

std::tuple<u64, u64, u64, u64> VP8::GetInterlacedOffsets() {
    return {};
}

VP9::VP9(Host1x::Host1x& host1x_, const Host1x::NvdecCommon::NvdecRegisters& regs_, s32 id_)
    : Decoder{host1x_, id_, regs_} {}

VP9::~VP9() = default;

std::span<const u8> VP9::ComposeFrame() {
    return {};
}

std::tuple<u64, u64> VP9::GetProgressiveOffsets() {
    return {};
}

std::tuple<u64, u64, u64, u64> VP9::GetInterlacedOffsets() {
    return {};
}

} // namespace Decoders

namespace Host1x {

Vic::Vic(Host1x& host1x_, s32 id_, u32 syncpt) noexcept
    : CDmaPusher{host1x_, id_}, id{id_}, syncpoint{syncpt} {}

Vic::~Vic() noexcept {}

void Vic::ProcessMethod(u32, u32) noexcept {}

} // namespace Host1x

} // namespace Tegra

namespace Common::Android::SoftwareKeyboard {

void InitJNI(JNIEnv*) {}
void CleanupJNI(JNIEnv*) {}

} // namespace Common::Android::SoftwareKeyboard

namespace Common::Android::WebBrowser {

void InitJNI(JNIEnv*) {}
void CleanupJNI(JNIEnv*) {}

} // namespace Common::Android::WebBrowser

void AndroidMultiplayer::NetworkShutdown() {}

// Declared inside id_cache.cpp's registration path; FFmpeg is not built here.
extern "C" jint InitFFmpegOnLoad(JavaVM*) {
    return 0;
}
