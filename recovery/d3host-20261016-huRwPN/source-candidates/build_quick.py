#!/usr/bin/env python3
import os
import shutil
import subprocess
import zipfile

ROOT = os.getcwd()
OUT_DIR = os.path.join(ROOT, "build")

# Copy the old APK and update just the .so
old_apk = os.path.join(OUT_DIR, "d3host-aligned.apk")
new_apk = os.path.join(OUT_DIR, "d3host-new.apk")
signed_apk = os.path.join(OUT_DIR, "d3host-updated.apk")
so_file = os.path.join(OUT_DIR, "libd3host.so")
keystore = os.path.join(OUT_DIR, "d3host-debug.keystore")

# Copy the APK
shutil.copy(old_apk, new_apk)

# Remove the old .so and add the new one
with zipfile.ZipFile(new_apk, 'a') as z:
    # List files
    files = z.namelist()
    if 'lib/arm64-v8a/libd3host.so' in files:
        print(f"Removing old libd3host.so from APK")
        # Can't remove from zip, need to recreate

# Recreate APK without the old .so
temp_dir = os.path.join(OUT_DIR, "temp_apk")
shutil.rmtree(temp_dir, ignore_errors=True)
os.makedirs(temp_dir)

with zipfile.ZipFile(old_apk, 'r') as z:
    for item in z.namelist():
        if item != 'lib/arm64-v8a/libd3host.so':
            z.extract(item, temp_dir)

# Create new APK
with zipfile.ZipFile(new_apk, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            filepath = os.path.join(root, file)
            arcname = os.path.relpath(filepath, temp_dir)
            z.write(filepath, arcname)
    # Add new .so
    z.write(so_file, 'lib/arm64-v8a/libd3host.so', compress_type=zipfile.ZIP_STORED)

print(f"Created {new_apk}")

# Sign it
apksigner = r"D:\workspace\Gdict\android_sdk\build-tools\36.0.0\apksigner.bat"
subprocess.run([
    "cmd.exe", "/d", "/c", apksigner, "sign",
    "--ks", keystore,
    "--ks-pass", "pass:android",
    "--key-pass", "pass:android",
    "--out", signed_apk,
    new_apk,
], check=True)

print(f"Signed APK: {signed_apk}")
print(f"Size: {os.path.getsize(signed_apk)} bytes")

# Clean up
shutil.rmtree(temp_dir, ignore_errors=True)
os.remove(new_apk)
