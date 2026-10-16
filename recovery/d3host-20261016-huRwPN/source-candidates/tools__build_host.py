# Compile the host (d3_host.c, d3_service.c, d3_jni.c). Does not build Java or an APK.
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NDK = r"D:\workspace\Gdict\android_sdk\ndk\28.2.13676358"
CLANG = os.path.join(
    NDK, "toolchains", "llvm", "prebuilt", "windows-x86_64", "bin", "clang.exe"
)
OUT_DIR = os.path.join(ROOT, "build")
OUT = os.path.join(OUT_DIR, "libd3host.so")
SRC = [
    os.path.join(ROOT, "host", "d3_host.c"),
    os.path.join(ROOT, "host", "d3_service.c"),
    os.path.join(ROOT, "host", "d3_jni.c"),
]


def main() -> None:
    if not os.path.isfile(CLANG):
        sys.exit("missing " + CLANG)
    os.makedirs(OUT_DIR, exist_ok=True)
    cmd = [
        CLANG,
        "--target=aarch64-linux-android34",
        "-fPIC",
        "-fno-stack-protector",
        "-ffixed-x18",
        "-fvisibility=hidden",
        "-O2",
        "-g",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-shared",
        "-Wl,-z,max-page-size=16384",
        "-Wl,--no-undefined",
        *SRC,
        "-llog",
        "-ldl",
        "-o",
        OUT,
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
