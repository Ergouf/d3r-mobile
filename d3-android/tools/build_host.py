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
    os.path.join(ROOT, "host", "d3_sync.c"),
    os.path.join(ROOT, "host", "d3_nvdrv.c"),
    os.path.join(ROOT, "host", "d3_audio.c"),
    os.path.join(ROOT, "host", "d3_jni.c"),
    # The hook entry stub: TPIDR_EL0 switch + body dispatch, encoded by the
    # assembler (hand written opcodes in C were wrong twice in a row).
    os.path.join(ROOT, "host", "hook_stub.S"),
]
GPU_LIB = os.path.join(ROOT, "build", "libeden_gpu.a")
PROBE_SRC = os.path.join(ROOT, "tools", "d3_probe.c")

# Native tests. Each test #includes the .c it exercises, so the exercised unit
# is NOT linked again. A test that #includes d3_host.c must link d3_sync.c
# (host.c calls into the sync module but does not include it); test_sync
# #includes both host.c and sync.c, so it links only d3_service.c.
test_stack_memory = [os.path.join(ROOT, "tests", "test_stack_memory.c"),
                     os.path.join(ROOT, "host", "d3_service.c"),
                     os.path.join(ROOT, "host", "hook_stub.S"),
                     os.path.join(ROOT, "host", "d3_sync.c")]
SERVICE_HOST_STUBS = os.path.join(ROOT, "tests", "service_host_stubs.c")
test_applet_focus = [os.path.join(ROOT, "tests", "test_applet_focus.c"), SERVICE_HOST_STUBS]
test_hipc_message = [os.path.join(ROOT, "tests", "test_hipc_message.c"), SERVICE_HOST_STUBS]
test_hid_service = [os.path.join(ROOT, "tests", "test_hid_service.c"), SERVICE_HOST_STUBS]
test_audio = [os.path.join(ROOT, "tests", "test_audio.c")]
test_hid_memory = [os.path.join(ROOT, "tests", "test_hid_memory.c"),
                   os.path.join(ROOT, "host", "d3_service.c"),
                   os.path.join(ROOT, "host", "d3_sync.c"),
                   os.path.join(ROOT, "host", "hook_stub.S")]
test_set_service = [os.path.join(ROOT, "tests", "test_set_service.c"), SERVICE_HOST_STUBS]
test_boot_sequence = [os.path.join(ROOT, "tests", "test_boot_sequence.c"),
                      os.path.join(ROOT, "host", "d3_service.c"),
                      os.path.join(ROOT, "host", "hook_stub.S"),
                      os.path.join(ROOT, "host", "d3_sync.c")]
test_signal_chain = [os.path.join(ROOT, "tests", "test_signal_chain.c"),
                     os.path.join(ROOT, "host", "d3_service.c"),
                     os.path.join(ROOT, "host", "d3_sync.c"),
                     os.path.join(ROOT, "host", "hook_stub.S")]
test_time_service = [os.path.join(ROOT, "tests", "test_time_service.c"), SERVICE_HOST_STUBS]
test_sync = [os.path.join(ROOT, "tests", "test_sync.c"),
             os.path.join(ROOT, "host", "d3_service.c"),
             os.path.join(ROOT, "host", "hook_stub.S")]

test_address_arbiter = [os.path.join(ROOT, "tests", "test_address_arbiter.c"),
                        os.path.join(ROOT, "host", "d3_service.c"),
                        os.path.join(ROOT, "host", "hook_stub.S")]

test_guest_tls = [os.path.join(ROOT, "tests", "test_guest_tls.c"),
                  os.path.join(ROOT, "tests", "test_guest_tls.S"),
                  os.path.join(ROOT, "host", "d3_service.c"),
                  os.path.join(ROOT, "host", "d3_sync.c"),
                  os.path.join(ROOT, "host", "hook_stub.S")]

test_save_filesystem = [os.path.join(ROOT, "tests", "test_save_filesystem.c"), SERVICE_HOST_STUBS]
test_keyboard = [os.path.join(ROOT, "tests", "test_keyboard.c"), SERVICE_HOST_STUBS]
test_nvdrv = [os.path.join(ROOT, "tests", "test_nvdrv.c")]
test_nvdrv_gpu = [os.path.join(ROOT, "tests", "test_nvdrv_gpu.c")]
test_startup_services = [os.path.join(ROOT, "tests", "test_startup_services.c"), SERVICE_HOST_STUBS]
test_directory = [os.path.join(ROOT, "tests", "test_directory.c"),
                  os.path.join(ROOT, "host", "d3_service.c"),
                  os.path.join(ROOT, "host", "d3_sync.c"),
                  os.path.join(ROOT, "host", "hook_stub.S")]
test_content = [os.path.join(ROOT, "tests", "test_content.c"),
                os.path.join(ROOT, "host", "d3_service.c"),
                os.path.join(ROOT, "host", "d3_sync.c"),
                os.path.join(ROOT, "host", "hook_stub.S")]

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


# Flags that make sense while compiling a translation unit (no link phase).
COMPILE_ONLY_FLAGS = [flag for flag in HOST_FLAGS
                      if flag != "-shared" and not flag.startswith("-Wl,")]


def build_host_with_gpu(clang: str, defines, out_dir: str, host_out: str) -> None:
    """Link the C host against the Eden GPU archive.

    The GPU archive is C++, so the C sources are compiled to objects first and
    linked with clang++ (static libc++ keeps the APK to a single shared object).
    """
    if not os.path.isfile(GPU_LIB):
        sys.exit("missing %s -- run d3-android/gpu/build_gpu.ps1 first" % GPU_LIB)

    clangxx = os.path.join(os.path.dirname(clang), "clang++.exe")
    obj_dir = os.path.join(out_dir, "host-obj")
    os.makedirs(obj_dir, exist_ok=True)
    defines = [*defines, "-DD3_WITH_GPU=1"]

    objects = []
    for src in HOST_SRC:
        obj = os.path.join(obj_dir, os.path.splitext(os.path.basename(src))[0] + ".o")
        compile_one([clang, *COMPILE_ONLY_FLAGS, *defines, "-c", src, "-o", obj], obj)
        objects.append(obj)

    link = [
        clangxx,
        "--target=aarch64-linux-android34",
        "-shared",
        "-fPIC",
        "-fvisibility=hidden",
        "-O2",
        "-g",
        "-Wl,-z,max-page-size=16384",
        "-Wl,--no-undefined",
        "-Wl,--exclude-libs,ALL",
        "-static-libstdc++",
        *defines,
        *objects,
        GPU_LIB,
        os.path.join(ROOT, "build", "adrenotools", "libadrenotools.a"),
        os.path.join(ROOT, "build", "adrenotools", "lib", "linkernsbypass", "liblinkernsbypass.a"),
        "-llog",
        "-laaudio",
        "-ldl",
        "-landroid",
        "-ljnigraphics",
        "-o",
        host_out,
    ]
    compile_one(link, host_out)


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
        "--with-gpu",
        action="store_true",
        help="Link build/libeden_gpu.a (Eden Vulkan stack) into libd3host.so",
    )
    parser.add_argument("--data-root", help="Absolute Android runtime data directory")
    parser.add_argument(
        "--private-root", help="Absolute Android application data directory"
    )
    parser.add_argument(
        "--build-probe",
        action="store_true",
        help="Also compile tools/d3_probe.c (with -ldl) into the same output directory",
    )
    parser.add_argument(
        "--build-tests",
        action="store_true",
        help="Compile-only: also build the native Android tests (test_stack_memory, "
        "test_applet_focus, test_hipc_message, test_set_service, test_boot_sequence, "
        "test_signal_chain, test_time_service, test_hid_service, test_hid_memory) "
        "into the output directory. Does not "
        "touch a device.",
    )
    parser.add_argument(
        "--build-gpu-tests",
        action="store_true",
        help="Also compile the standalone CPU write-tracker Android regression test",
    )
    args = parser.parse_args()

    clang = clang_path(args.ndk)
    if not os.path.isfile(clang):
        sys.exit("missing clang: " + clang)

    if args.sandbox_root and (args.data_root or args.private_root):
        parser.error("--sandbox-root cannot be combined with --data-root/--private-root")
    defines = sandbox_defines(args.sandbox_root) if args.sandbox_root else []
    for name, value in (("D3_DATA_ROOT", args.data_root), ("D3_PRIVATE_ROOT", args.private_root)):
        if value is None:
            continue
        if not value.startswith("/") or any(char in value for char in "\x00\n\r"):
            parser.error("%s must be an absolute Android path without NUL/newlines" % name)
        defines.append("-D" + name + "=" + c_literal(value.rstrip("/") or "/"))

    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)

    host_out = os.path.join(out_dir, "libd3host.so")
    if args.with_gpu:
        build_host_with_gpu(clang, defines, out_dir, host_out)
    else:
        compile_one(
            [clang, *HOST_FLAGS, *defines, *HOST_SRC, "-llog", "-laaudio", "-landroid", "-ldl", "-o", host_out],
            host_out,
        )

    if args.build_probe:
        probe_out = os.path.join(out_dir, "d3_probe")
        compile_one(
            [clang, *PROBE_FLAGS, *defines, PROBE_SRC, "-ldl", "-o", probe_out],
            probe_out,
        )

    if args.build_gpu_tests:
        output = os.path.join(out_dir, "test_cpu_write_tracker")
        clangxx = os.path.join(os.path.dirname(clang), "clang++.exe")
        compile_one([clangxx, *PROBE_FLAGS, "-std=c++20", "-static-libstdc++",
                     os.path.join(ROOT, "tests", "test_cpu_write_tracker.cpp"),
                     "-o", output], output)

    if args.build_tests:
        display_test = os.path.join(out_dir, "test_display")
        compile_one([clang, *PROBE_FLAGS, os.path.join(ROOT, "tests", "test_display.c"),
                     "-o", display_test], display_test)
        for name, src in (("test_stack_memory", test_stack_memory),
                          ("test_applet_focus", test_applet_focus),
                          ("test_hipc_message", test_hipc_message),
                          ("test_hid_service", test_hid_service),
                          ("test_audio", test_audio),
                          ("test_hid_memory", test_hid_memory),
                          ("test_set_service", test_set_service),
                          ("test_boot_sequence", test_boot_sequence),
                          ("test_signal_chain", test_signal_chain),
                          ("test_time_service", test_time_service),
                          ("test_sync", test_sync),
                          ("test_address_arbiter", test_address_arbiter),
                          ("test_guest_tls", test_guest_tls),
                          ("test_save_filesystem", test_save_filesystem),
                          ("test_keyboard", test_keyboard),
                          ("test_nvdrv", test_nvdrv),
                          ("test_nvdrv_gpu", test_nvdrv_gpu),
                          ("test_startup_services", test_startup_services),
                          ("test_content", test_content),
                          ("test_directory", test_directory)):
            out = os.path.join(out_dir, name)
            compile_one(
                [clang, *PROBE_FLAGS, *defines, *src,
                 *([] if name == "test_nvdrv_gpu" else [os.path.join(ROOT, "host", "d3_nvdrv.c")]),
                 *([] if name == "test_audio" else [os.path.join(ROOT, "host", "d3_audio.c")]),
                 "-llog", "-laaudio", "-ldl", "-o", out],
                out,
            )


if __name__ == "__main__":
    main()
