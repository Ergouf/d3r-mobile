#!/usr/bin/env python3
"""Build a normal or optional OEM game-identity APK with matching native paths.

Does not install/uninstall apps or change device data. OEM features depend on
the device's firmware, allowlist and signature policy.
"""
import argparse
import pathlib
import subprocess
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_adreno

ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["recovery", "genshin", "genshin-bilibili"], default="recovery")
    parser.add_argument("--guest", required=True)
    parser.add_argument("--keystore", required=True)
    parser.add_argument("--sdk", default=r"D:\workspace\Gdict\android_sdk")
    parser.add_argument("--ndk", default=r"D:\workspace\Gdict\android_sdk\ndk\28.2.13676358")
    args = parser.parse_args()
    package = {"genshin": "com.miHoYo.Yuanshen",
               "genshin-bilibili": "com.miHoYo.ys.bilibili"}.get(args.profile, "com.d3mobile.host.recovery")
    private = "/data/user/0/" + package
    output = ROOT / "build" / ("android-" + args.profile)
    build_adreno.build(args.sdk, args.ndk)
    subprocess.run(["pwsh", "-File", str(ROOT / "gpu/build_gpu.ps1")], check=True)
    subprocess.run([sys.executable, "-I", str(ROOT / "tools/build_host.py"), "--with-gpu", "--ndk", args.ndk,
        "--private-root", private, "--data-root", private + "/files/runtime", "--output-dir", str(output / "host")], check=True)
    subprocess.run([sys.executable, "-I", str(ROOT / "tools/build_apk.py"), "--package", package, "--sdk", args.sdk,
        "--host", str(output / "host/libd3host.so"), "--guest", args.guest, "--keystore", args.keystore,
        "--driver-hooks-dir", str(ROOT / "build/adrenotools/src/hook"), "--output-dir", str(output / "apk")], check=True)

if __name__ == "__main__":
    main()
