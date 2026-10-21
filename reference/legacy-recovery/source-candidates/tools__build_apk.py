import os
import shutil
import subprocess
import sys
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = r"D:\workspace\Gdict\android_sdk"
BUILD_TOOLS = os.path.join(SDK, "build-tools", "36.0.0")
PLATFORM = os.path.join(SDK, "platforms", "android-36")
JAVA_HOME = os.path.join(SDK, "jdk-17.0.12+7")
OUT_DIR = os.path.join(ROOT, "build")
CLASSES_DIR = os.path.join(OUT_DIR, "classes")
DEX_DIR = os.path.join(OUT_DIR, "dex")
MANIFEST = os.path.join(ROOT, "app", "AndroidManifest.xml")
JAVA_SOURCE = os.path.join(ROOT, "app", "src", "com", "d3mobile", "host", "MainActivity.java")
ANDROID_JAR = os.path.join(PLATFORM, "android.jar")
UNSIGNED_APK = os.path.join(OUT_DIR, "d3host-unsigned.apk")
ALIGNED_APK = os.path.join(OUT_DIR, "d3host-aligned.apk")
APK = os.path.join(OUT_DIR, "d3host.apk")
KEYSTORE = os.path.join(OUT_DIR, "d3host-debug.keystore")


def tool(name):
    path = os.path.join(BUILD_TOOLS, name)
    if not os.path.isfile(path):
        raise SystemExit("missing " + path)
    return path


def java_tool(name):
    path = os.path.join(JAVA_HOME, "bin", name)
    if not os.path.isfile(path):
        raise SystemExit("missing " + path)
    return path


def run(command):
    print(" ".join(command))
    subprocess.run(command, check=True)


def add_file(apk_path, source, archive_name):
    with zipfile.ZipFile(apk_path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, archive_name, compress_type=zipfile.ZIP_STORED)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    shutil.rmtree(CLASSES_DIR, ignore_errors=True)
    shutil.rmtree(DEX_DIR, ignore_errors=True)
    os.makedirs(CLASSES_DIR)
    os.makedirs(DEX_DIR)

    javac = java_tool("javac.exe")
    java = java_tool("java.exe")
    keytool = java_tool("keytool.exe")
    d8 = tool("d8.bat")
    aapt2 = tool("aapt2.exe")
    zipalign = tool("zipalign.exe")
    apksigner = tool("apksigner.bat")

    run([
        javac,
        "-encoding", "UTF-8",
        "--release", "11",
        "-classpath", ANDROID_JAR,
        "-d", CLASSES_DIR,
        JAVA_SOURCE,
    ])
    run([
        "cmd.exe", "/d", "/c", d8,
        "--min-api", "34",
        "--output", DEX_DIR,
        *[
            os.path.join(directory, filename)
            for directory, _, filenames in os.walk(CLASSES_DIR)
            for filename in filenames
            if filename.endswith(".class")
        ],
    ])
    run([
        aapt2, "link",
        "-o", UNSIGNED_APK,
        "-I", ANDROID_JAR,
        "--manifest", MANIFEST,
        "--min-sdk-version", "34",
        "--target-sdk-version", "36",
        "--version-code", "1",
        "--version-name", "1.0",
    ])

    add_file(UNSIGNED_APK, os.path.join(DEX_DIR, "classes.dex"), "classes.dex")
    add_file(UNSIGNED_APK, os.path.join(OUT_DIR, "libd3host.so"), "lib/arm64-v8a/libd3host.so")
    add_file(UNSIGNED_APK, os.path.join(OUT_DIR, "libd3guest.so"), "lib/arm64-v8a/libd3guest.so")

    run([zipalign, "-f", "-P", "16", "4", UNSIGNED_APK, ALIGNED_APK])
    if not os.path.isfile(KEYSTORE):
        run([
            keytool, "-genkeypair",
            "-keystore", KEYSTORE,
            "-storepass", "android",
            "-keypass", "android",
            "-alias", "androiddebugkey",
            "-dname", "CN=Android Debug,O=Android,C=US",
            "-keyalg", "RSA",
            "-keysize", "2048",
            "-validity", "10000",
        ])
    run([
        "cmd.exe", "/d", "/c", apksigner, "sign",
        "--ks", KEYSTORE,
        "--ks-pass", "pass:android",
        "--key-pass", "pass:android",
        "--out", APK,
        ALIGNED_APK,
    ])
    run([
        "cmd.exe", "/d", "/c", apksigner, "verify", "--verbose", APK,
    ])
    print("wrote %s (%d bytes)" % (APK, os.path.getsize(APK)))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
