#!/usr/bin/env python3
"""Build pinned libadrenotools and its packaged hooks for the Android host."""
import argparse
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVISION = "8fae8ce254dfc1344527e05301e43f37dea2df80"

def build(sdk, ndk):
    source = ROOT / "gpu/third_party/libadrenotools"
    if not source.exists():
        subprocess.run(["git", "clone", "https://github.com/bylaws/libadrenotools.git", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", REVISION], check=True)
        subprocess.run(["git", "-C", str(source), "submodule", "update", "--init", "--recursive"], check=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise RuntimeError("Unexpected libadrenotools revision: " + revision)
    patch = ROOT / "gpu/patches/adrenotools-mali-isolation.patch"
    applied = subprocess.run(["git", "-C", str(source), "apply", "--reverse", "--check", str(patch)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if applied.returncode:
        subprocess.run(["git", "-C", str(source), "apply", "--check", str(patch)], check=True)
        subprocess.run(["git", "-C", str(source), "apply", str(patch)], check=True)
    cmake_root = pathlib.Path(sdk) / "cmake/3.22.1/bin"
    cmake = str(cmake_root / "cmake.exe")
    output = ROOT / "build/adrenotools"
    subprocess.run([cmake, "-S", str(source), "-B", str(output), "-G", "Ninja",
        "-DCMAKE_MAKE_PROGRAM=" + str(cmake_root / "ninja.exe"),
        "-DCMAKE_TOOLCHAIN_FILE=" + str(pathlib.Path(ndk) / "build/cmake/android.toolchain.cmake"),
        "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-34",
        "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF"], check=True)
    subprocess.run([cmake, "--build", str(output), "-j", "8"], check=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", default=r"D:\workspace\Gdict\android_sdk")
    parser.add_argument("--ndk", default=r"D:\workspace\Gdict\android_sdk\ndk\28.2.13676358")
    args = parser.parse_args()
    build(args.sdk, args.ndk)
