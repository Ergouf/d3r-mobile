package com.d3mobile.host;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.*;
import java.util.zip.*;

/** Settings are committed before renderer creation, and changed on the next launch. */
final class GraphicsSettings {
    static final int IMPORT_DRIVER = 517;
    private final Activity activity;
    private final SharedPreferences prefs;
    GraphicsSettings(Activity activity) {
        this.activity = activity;
        prefs = activity.getSharedPreferences("graphics", 0);
        if (prefs.getBoolean("custom", false) && prefs.getString("driver", "").equals(prefs.getString("launchedDriver", "-"))) {
            ActivityManager manager = (ActivityManager)activity.getSystemService(Activity.ACTIVITY_SERVICE);
            for (ApplicationExitInfo exit : manager.getHistoricalProcessExitReasons(null, prefs.getInt("launchedPid", -1), 1)) {
                if (exit.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE) {
                    prefs.edit().putBoolean("custom", false).commit();
                    Toast.makeText(activity, "上次运行异常，已恢复系统 GPU 驱动，可在画面设置重新选择", Toast.LENGTH_LONG).show();
                }
            }
        }
        prefs.edit().putString("launchedDriver", driverName().isEmpty() ? "" : prefs.getString("driver", ""))
            .putInt("launchedPid", android.os.Process.myPid()).commit();
    }
    int scale() { return prefs.getInt("scale", 10) == 15 ? 15 : 10; }
    String driverName() { return prefs.getBoolean("custom", false) ? prefs.getString("library", "") : ""; }
    String driverDirectory() { return new File(activity.getFilesDir(), prefs.getString("driver", "drivers/none")).getAbsolutePath(); }

    void show() {
        final String[] items = {"渲染倍数：" + (scale() == 15 ? "1.5×" : "1.0×"),
            "GPU 驱动：" + (driverName().isEmpty() ? "系统 Vulkan" : prefs.getString("driverLabel", "自定义")),
            "导入 Adreno / Turnip 驱动 ZIP", "设置保存后，下次启动生效"};
        new AlertDialog.Builder(activity).setTitle("画面与 GPU")
            .setItems(items, (dialog, which) -> {
                if (which == 0) new AlertDialog.Builder(activity).setTitle("渲染倍数")
                    .setSingleChoiceItems(new String[]{"1.0×（性能优先）", "1.5×（更清晰，GPU 负载更高）"}, scale() == 15 ? 1 : 0,
                        (d, n) -> { prefs.edit().putInt("scale", n == 1 ? 15 : 10).apply(); d.dismiss(); show(); }).show();
                if (which == 1) {
                    boolean available = !prefs.getString("library", "").isEmpty();
                    String[] names = available ? new String[]{"系统 Vulkan", prefs.getString("driverLabel", "自定义驱动")} : new String[]{"系统 Vulkan"};
                    new AlertDialog.Builder(activity).setTitle("GPU 驱动")
                        .setSingleChoiceItems(names, driverName().isEmpty() ? 0 : 1,
                            (d, n) -> { prefs.edit().putBoolean("custom", n == 1).apply(); d.dismiss(); show(); }).show();
                }
                if (which == 2) {
                    Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
                    activity.startActivityForResult(intent, IMPORT_DRIVER);
                }
            }).setNegativeButton("返回游戏", null).show();
    }

    void importDriver(Uri uri) {
        new Thread(() -> {
            File staging = new File(activity.getFilesDir(), "drivers/driver-" + System.nanoTime());
            try {
                if (!staging.mkdirs()) throw new IOException("无法创建驱动目录");
                long total = 0;
                int entries = 0;
                try (InputStream input = activity.getContentResolver().openInputStream(uri);
                     ZipInputStream zip = new ZipInputStream(input)) {
                    ZipEntry entry;
                    byte[] buffer = new byte[65536];
                    while ((entry = zip.getNextEntry()) != null) {
                        if (++entries > 512) throw new IOException("ZIP 文件过多");
                        File target = new File(staging, entry.getName());
                        if (!target.getCanonicalPath().startsWith(staging.getCanonicalPath() + File.separator))
                            throw new IOException("驱动 ZIP 路径无效");
                        if (entry.isDirectory()) { target.mkdirs(); continue; }
                        if (!target.getParentFile().isDirectory() && !target.getParentFile().mkdirs()) throw new IOException("无法创建目录");
                        try (OutputStream output = new FileOutputStream(target)) {
                            int count;
                            while ((count = zip.read(buffer)) != -1) {
                                total += count;
                                if (total > 256L * 1024 * 1024) throw new IOException("驱动解压超过 256 MB");
                                output.write(buffer, 0, count);
                            }
                        }
                    }
                }
                File metadata = new File(staging, "meta.json");
                if (!metadata.isFile() || metadata.length() > 65536) throw new IOException("缺少有效 meta.json");
                JSONObject json = new JSONObject(new String(java.nio.file.Files.readAllBytes(metadata.toPath()), "UTF-8"));
                if (json.optInt("minApi", 0) > Build.VERSION.SDK_INT) throw new IOException("驱动不支持当前 Android 版本");
                String library = json.getString("libraryName");
                if (!library.matches("[A-Za-z0-9_.+-]+\\.so")) throw new IOException("驱动库名无效");
                File so = new File(staging, library);
                try (InputStream elf = new FileInputStream(so)) {
                    byte[] header = new byte[20];
                    if (elf.read(header) != 20 || header[0] != 127 || header[1] != 'E' || header[2] != 'L' || header[3] != 'F'
                            || header[4] != 2 || header[5] != 1 || (header[18] & 255) != 183 || header[19] != 0)
                        throw new IOException("需要 ARM64 ELF 驱动");
                }
                prefs.edit().putString("library", library).putString("driver", "drivers/" + staging.getName())
                    .putString("driverLabel", json.optString("name", library)).putBoolean("custom", true).commit();
                activity.runOnUiThread(() -> Toast.makeText(activity, "驱动已导入，下次启动生效", Toast.LENGTH_LONG).show());
            } catch (Exception error) {
                remove(staging);
                activity.runOnUiThread(() -> new AlertDialog.Builder(activity).setTitle("导入失败")
                    .setMessage(error.getMessage()).setPositiveButton("确定", null).show());
            }
        }, "driver-import").start();
    }
    private static void remove(File file) {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) remove(child);
        file.delete();
    }
}
