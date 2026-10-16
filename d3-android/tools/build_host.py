#!/usr/bin/env python3
# Compile the host (d3_host.c, d3_service.c, d3_jni.c) and optionally the probe.
# Does not build Java or an APK, install anything, or touch a device.
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWN_NDK = r"D:\workspace\Gdict\android_sdk\ndk\28.2.13676358"

HOST_SRC = [
    os.path.join(ROOT, "host", "d3_host.c"),
    os.path.join(ROOT, "host", "d3_service.c"),
    os.path.join(ROOT, "host", "d3_jni.c"),
]
PROBE_SRC = os.path.join(ROOT, "tools", "d3_probe.c")

# Strict flags preserved verbatim from the original build_host.py.
HOST_FLAGS = [
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
]
# The probe is an executable (has main), so it is not linked with -shared.
PROBE_FLAGS = [
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
]


def clang_path(ndk: str) -> str:
    return os.path.join(
        ndk, "toolchains", "llvm", "prebuilt", "windows-x86_64", "bin", "clang.exe"
    )


def c_literal(value: str) -> str:
    """Render a path as a C string literal (escape backslash and quote)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def sandbox_defines(sandbox_root: str):
    """Validate an absolute Android sandbox path and build the -D macros.

    Without this, the compiled-in paths stay at the installed app defaults.
    """
    if "\x00" in sandbox_root or "\n" in sandbox_root or "\r" in sandbox_root:
        sys.exit("invalid --sandbox-root: contains NUL or a newline")
    if not sandbox_root.startswith("/"):
        sys.exit("invalid --sandbox-root: must be an absolute Android path (start with '/')")
    base = sandbox_root.rstrip("/")
    return [
        "-DD3_DATA_ROOT=" + c_literal(base + "/data"),
        "-DD3_PRIVATE_ROOT=" + c_literal(base + "/private"),
    ]


def compile_one(cmd, out_path: str) -> None:
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("wrote %s (%d bytes)" % (out_path, os.path.getsize(out_path)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile the D3 host shared library (and optionally the probe)."
    )
    parser.add_argument(
        "--ndk",
        default=os.environ.get("ANDROID_NDK_HOME") or KNOWN_NDK,
        help="NDK root (default: $ANDROID_NDK_HOME or the known install path)",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(ROOT, "build"),
        help="Output directory (default: <project>/build)",
    )
    parser.add_argument(
        "--sandbox-root",
        default=None,
        metavar="ABS_PATH",
        help="Absolute Android path; sets -DD3_DATA_ROOT/-DD3_PRIVATE_ROOT "
        "(default: installed app paths from the headers)",
    )
    parser.add_argument(
        "--build-probe",
        action="store_true",
        help="Also compile tools/d3_probe.c (with -ldl) into the same output directory",
    )
    args = parser.parse_args()

    clang = clang_path(args.ndk)
    if not os.path.isfile(clang):
        sys.exit("missing clang: " + clang)

    defines = sandbox_defines(args.sandbox_root) if args.sandbox_root else []

    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)

    host_out = os.path.join(out_dir, "libd3host.so")
    compile_one(
        [clang, *HOST_FLAGS, *defines, *HOST_SRC, "-llog", "-ldl", "-o", host_out],
        host_out,
    )

    if args.build_probe:
        probe_out = os.path.join(out_dir, "d3_probe")
        compile_one(
            [clang, *PROBE_FLAGS, *defines, PROBE_SRC, "-ldl", "-o", probe_out],
            probe_out,
        )


if __name__ == "__main__":
    main()
