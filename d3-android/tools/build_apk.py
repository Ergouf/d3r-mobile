#!/usr/bin/env python3
"""Package the offline D3 recovery shell into a debug APK.

Builds ONLY the thin Java shell APK (d3-android/app): it compiles the single
MainActivity, dexes it, packs the caller-supplied host and guest shared
libraries, aligns, and signs with a local debug keystore.

It deliberately does NOT compile the host or guest. Both are required inputs
(--host, --guest) so a stale or accidentally-picked binary is impossible: this
tool never globs for or chooses a "latest" .so.

No device is touched: no install, no adb. The only files written are inside
--output-dir (the APK, its metadata JSON, and the local debug keystore).

Reads only:
  <sdk>/platforms/android-36/android.jar        (compile + link against)
  <sdk>/build-tools/36.0.0/aapt2.exe
  <sdk>/build-tools/36.0.0/zipalign.exe
  <sdk>/build-tools/36.0.0/lib/d8.jar
  <sdk>/build-tools/36.0.0/lib/apksigner.jar
  <jdk>/bin/{javac,java,keytool}.exe

The JDK is never launched via its .bat wrappers: every tool is a `java -cp`/
`java -jar`/`.exe` subprocess with an explicit argv (shell=False), so
JAVA_HOME/profile handling cannot leak in.

Run with:  python -I tools/build_apk.py --host ... --guest ...
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "app", "AndroidManifest.xml")
SRC_DIR = os.path.join(ROOT, "app", "src")

DEFAULT_SDK = r"D:\workspace\Gdict\android_sdk"
BUILD_TOOLS_VERSION = "36.0.0"
PLATFORM = "android-36"

PACKAGE_NAME = "com.d3mobile.host.recovery"
OEM_PACKAGES = ("com.miHoYo.Yuanshen", "com.miHoYo.ys.bilibili")
MAIN_CLASS = "com.d3mobile.host.MainActivity"
ABI = "arm64-v8a"
APK_NAME = "d3host-recovery-debug.apk"
META_NAME = "d3host-recovery-debug.json"
KEYSTORE_NAME = "local-debug.keystore"
KEY_ALIAS = "androiddebugkey"
# Documented, public debug credentials: local test only, never production.
STORE_PASS = "android"
KEY_PASS = "android"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd):
    """Run an explicit argv with shell=False; abort on any non-zero exit."""
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def require_file(path, what):
    if not os.path.isfile(path):
        sys.exit("missing %s: %s" % (what, path))
    if os.path.getsize(path) == 0:
        sys.exit("empty %s: %s" % (what, path))


def find_jdk(sdk_root, explicit):
    if explicit:
        return explicit
    # Prefer the JDK installed next to the SDK, as this workspace does.
    candidate = os.path.join(sdk_root, "jdk-17.0.12+7")
    if os.path.isfile(os.path.join(candidate, "bin", "javac.exe")):
        return candidate
    for name in sorted(os.listdir(sdk_root)):
        if name.lower().startswith("jdk"):
            p = os.path.join(sdk_root, name)
            if os.path.isfile(os.path.join(p, "bin", "javac.exe")):
                return p
    return None


def jdk_tool(jdk, name):
    exe = os.path.join(jdk, "bin", name + (".exe" if os.name == "nt" else ""))
    require_file(exe, "JDK tool " + name)
    return exe


def ensure_keystore(keytool, keystore_path):
    """Create the local debug keystore once; reuse it on later runs."""
    if os.path.isfile(keystore_path):
        print("reusing debug keystore %s" % keystore_path)
        return
    print("generating local debug keystore %s (debug-only, not for release)"
          % keystore_path)
    run([keytool, "-genkeypair", "-v",
         "-keystore", keystore_path,
         "-alias", KEY_ALIAS,
         "-storepass", STORE_PASS,
         "-keypass", KEY_PASS,
         "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
         "-dname", "CN=D3HOST Recovery Debug,O=Local Test,C=CN"])


def collect_java_sources(src_dir):
    sources = []
    for base, _dirs, files in os.walk(src_dir):
        for name in files:
            if name.endswith(".java"):
                sources.append(os.path.join(base, name))
    if not sources:
        sys.exit("no .java sources under " + src_dir)
    return sources


def pack_apk(tmp, linked_apk, host_so, guest_so, dex_dir, driver_hooks=None):
    """Insert classes.dex and the arm64 libs into the aapt2-linked APK.

    Native libraries are stored uncompressed so zipalign -P 16 can page-align
    them for 16 KiB-page devices.
    """
    classes_dex = os.path.join(dex_dir, "classes.dex")
    require_file(classes_dex, "dexed classes.dex")

    packed = os.path.join(tmp, "packed.apk")
    lib_prefix = "lib/%s/" % ABI
    with zipfile.ZipFile(linked_apk, "r") as src:
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                dst.writestr(item, src.read(item.filename))
            dst.write(classes_dex, "classes.dex")
            for so_path, so_name in ((host_so, "libd3host.so"),
                                     (guest_so, "libd3guest.so")):
                # ZIP_STORED keeps the .so uncompressed for -P 16 alignment.
                dst.write(so_path, lib_prefix + so_name, zipfile.ZIP_STORED)
            for hook in driver_hooks or []:
                dst.write(hook, lib_prefix + os.path.basename(hook), zipfile.ZIP_STORED)
    return packed


def main():
    parser = argparse.ArgumentParser(
        description="Package the offline D3 recovery debug APK "
                    "(requires a freshly rebuilt host.so and the preserved guest.so).")
    parser.add_argument("--host", required=True,
                        help="Path to a freshly rebuilt libd3host.so (required)")
    parser.add_argument("--guest", required=True,
                        help="Path to the preserved libd3guest.so (required)")
    parser.add_argument("--sdk", default=DEFAULT_SDK,
                        help="Android SDK root (default: %s)" % DEFAULT_SDK)
    parser.add_argument("--jdk", default=None,
                        help="JDK root (default: the jdk-* directory under --sdk)")
    parser.add_argument("--output-dir",
                        default=os.path.join(ROOT, "build", "apk-recovery"),
                        help="Output directory for the APK, metadata and keystore "
                             "(default: <project>/build/apk-recovery)")
    parser.add_argument("--keystore", help="Existing debug keystore to reuse across output directories")
    parser.add_argument("--package", choices=[PACKAGE_NAME, *OEM_PACKAGES], default=PACKAGE_NAME,
                        help="Optional OEM game identity; requires a host compiled for this package's private root")
    parser.add_argument("--driver-hooks-dir", help="Built libadrenotools src/hook directory")
    args = parser.parse_args()

    host_so = os.path.abspath(args.host)
    guest_so = os.path.abspath(args.guest)
    sdk = os.path.abspath(args.sdk)
    output_dir = os.path.abspath(args.output_dir)

    require_file(host_so, "host library (--host)")
    require_file(guest_so, "guest library (--guest)")
    require_file(MANIFEST, "AndroidManifest.xml")
    driver_hooks = []
    if args.driver_hooks_dir:
        for name in ("libhook_impl.so", "libmain_hook.so", "libfile_redirect_hook.so", "libgsl_alloc_hook.so"):
            path = os.path.abspath(os.path.join(args.driver_hooks_dir, name))
            require_file(path, "Adreno driver hook")
            driver_hooks.append(path)

    jdk = find_jdk(sdk, args.jdk)
    if not jdk:
        sys.exit("could not find a JDK under %s; pass --jdk explicitly" % sdk)
    javac = jdk_tool(jdk, "javac")
    java = jdk_tool(jdk, "java")
    keytool = jdk_tool(jdk, "keytool")

    bt = os.path.join(sdk, "build-tools", BUILD_TOOLS_VERSION)
    aapt2 = os.path.join(bt, "aapt2.exe" if os.name == "nt" else "aapt2")
    zipalign = os.path.join(bt, "zipalign.exe" if os.name == "nt" else "zipalign")
    d8_jar = os.path.join(bt, "lib", "d8.jar")
    apksigner_jar = os.path.join(bt, "lib", "apksigner.jar")
    android_jar = os.path.join(sdk, "platforms", PLATFORM, "android.jar")

    require_file(aapt2, "aapt2")
    require_file(zipalign, "zipalign")
    require_file(d8_jar, "d8.jar")
    require_file(apksigner_jar, "apksigner.jar")
    require_file(android_jar, "android.jar")

    os.makedirs(output_dir, exist_ok=True)
    apk_out = os.path.join(output_dir, APK_NAME)
    meta_out = os.path.join(output_dir, META_NAME)
    keystore_path = os.path.abspath(args.keystore) if args.keystore else os.path.join(output_dir, KEYSTORE_NAME)
    if args.keystore:
        require_file(keystore_path, "existing debug keystore (--keystore)")

    # Fresh work dir per run so stale classes/dex from a previous build cannot
    # be picked up.
    tmp = tempfile.mkdtemp(prefix="d3apk-")
    try:
        # 1. Link the manifest/resources into a base APK (no res/ needed).
        linked_apk = os.path.join(tmp, "base.apk")
        run([aapt2, "link",
             "-o", linked_apk,
             "-I", android_jar,
             "--manifest", MANIFEST,
             "--rename-manifest-package", args.package,
             "--min-sdk-version", "34",
             "--target-sdk-version", "36",
             "--version-code", "1",
             "--version-name", "1.0"])

        # 2. Compile the Java shell against the Android boot classpath.
        sources = collect_java_sources(SRC_DIR)
        classes_dir = os.path.join(tmp, "classes")
        os.makedirs(classes_dir, exist_ok=True)
        run([javac, "-encoding", "UTF-8", "-source", "8", "-target", "8",
             "-bootclasspath", os.pathsep.join([android_jar, os.path.join(bt, "core-lambda-stubs.jar")]),
             "-d", classes_dir] + sources)

        # 3. Dex (invoke D8 through java -cp, never d8.bat). D8 rejects a bare
        #    directory, so bundle the compiled classes into a jar first.
        classes_jar = os.path.join(tmp, "classes.jar")
        with zipfile.ZipFile(classes_jar, "w", zipfile.ZIP_DEFLATED) as jar:
            for base, _dirs, files in os.walk(classes_dir):
                for name in files:
                    full = os.path.join(base, name)
                    jar.write(full, os.path.relpath(full, classes_dir))
        dex_dir = os.path.join(tmp, "dex")
        os.makedirs(dex_dir, exist_ok=True)
        run([java, "-cp", d8_jar, "com.android.tools.r8.D8",
             "--min-api", "34", "--output", dex_dir, classes_jar])

        # 4. Pack resources + classes.dex + libs into one unsigned APK.
        packed = pack_apk(tmp, linked_apk, host_so, guest_so, dex_dir, driver_hooks)

        # 5. Page-align (16 KiB page size for .so) for 16 KiB-page devices.
        aligned = os.path.join(tmp, "aligned.apk")
        run([zipalign, "-P", "16", "-f", "4", packed, aligned])

        # 6. Sign with the local debug keystore (in place), then verify.
        ensure_keystore(keytool, keystore_path)
        run([java, "-jar", apksigner_jar, "sign",
             "--ks", keystore_path,
             "--ks-key-alias", KEY_ALIAS,
             "--ks-pass", "pass:" + STORE_PASS,
             "--key-pass", "pass:" + KEY_PASS,
             aligned])
        run([java, "-jar", apksigner_jar, "verify", "--verbose", aligned])

        shutil.move(aligned, apk_out)

        metadata = {
            "package": args.package,
            "driver_hooks": [{"name": os.path.basename(p), "sha256": sha256_file(p)} for p in driver_hooks],
            "label": "D3HOST Recovery",
            "main_class": MAIN_CLASS,
            "abi": ABI,
            "min_sdk": 34,
            "target_sdk": 36,
            "apk": os.path.basename(apk_out),
            "apk_sha256": sha256_file(apk_out),
            "host_so": {"path": host_so, "sha256": sha256_file(host_so),
                        "size": os.path.getsize(host_so)},
            "guest_so": {"path": guest_so, "sha256": sha256_file(guest_so),
                         "size": os.path.getsize(guest_so)},
            "signed": True,
            "signing_keystore": KEYSTORE_NAME,
            "signing_key_alias": KEY_ALIAS,
        }
        with open(meta_out, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except subprocess.CalledProcessError as e:
        print("build failed; work dir kept for inspection: %s" % tmp,
              file=sys.stderr)
        sys.exit("tool failed with exit code %s: %s" % (e.returncode, e.cmd))
    except BaseException:
        print("build failed; work dir kept for inspection: %s" % tmp,
              file=sys.stderr)
        raise
    else:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    print("wrote %s (%d bytes)" % (apk_out, os.path.getsize(apk_out)))
    print("wrote %s" % meta_out)
    print("package %s | host sha256 %s" % (args.package, metadata["host_so"]["sha256"]))
    print("install with the device tooling of your choice (this script does not "
          "install anything).")


if __name__ == "__main__":
    main()
