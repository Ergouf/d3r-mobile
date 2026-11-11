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
    private final MainActivity activity;
    private final SharedPreferences prefs;
    GraphicsSettings(MainActivity activity) {
        this.activity = activity;
        prefs = activity.getSharedPreferences("graphics", 0);
        if (prefs.getInt("scale", 10) == 7) {
            prefs.edit().putInt("scale", 10).commit();
            android.util.Log.i("D3Recovery", "restored 1.0x rendering to preserve game text");
        }
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
    int scale() { return PresentationPolicy.textSafeScale(prefs.getInt("scale", 10)); }
    int frameCap() { return PresentationPolicy.frameCap(prefs.getInt("frameCap", 60)); }
    int refreshRate() {
        int value = prefs.getInt("refreshRate", PresentationPolicy.refreshForCap(frameCap()));
        return value == 72 || value == 90 || value == 120 ? value : 60;
    }
    boolean widescreen() { return prefs.getBoolean("widescreen", true); }
    String driverName() { return prefs.getBoolean("custom", false) ? prefs.getString("library", "") : ""; }
    String driverDirectory() { return new File(activity.getFilesDir(), prefs.getString("driver", "drivers/none")).getAbsolutePath(); }

    void show() {
        final String[] renderNames = {"1.0×（标准）", "1.5×（更清晰，GPU 负载更高）",
                "场景 87.5% 线性，界面与文字 1×", "场景 75% 线性，界面与文字 1×",
                "场景 62.5% 线性，界面与文字 1×"};
        final int[] renderModes = {10, 15, PresentationPolicy.SCENE_7_8,
                PresentationPolicy.SCENE_FSR, PresentationPolicy.SCENE_5_8};
        int selectedRender = 0;
        for (int i = 0; i < renderModes.length; ++i) if (scale() == renderModes[i]) selectedRender = i;
        final int renderIndex = selectedRender;
        final String[] items = {"渲染方式：" + renderNames[renderIndex],
            "下次启动驱动：" + (driverName().isEmpty() ? "系统 Vulkan" : prefs.getString("driverLabel", "自定义")),
            "导入 GPU 驱动 ZIP（Adreno / Turnip / Mali）", "虚拟手柄与界面",
            "本次驱动状态：" + activity.nativeDriverStatus(),
            "原生宽屏：" + (widescreen() ? "开启" : "16:9 基线") + "（重启生效）", "渲染倍数和驱动重启生效",
            "屏幕刷新率请求：" + refreshRate() + " Hz（重启生效）",
            "游戏帧率上限：" + frameCap() + " fps（重启生效）"};
        new AlertDialog.Builder(activity).setTitle("画面与 GPU")
            .setItems(items, (dialog, which) -> {
                if (which == 0) new AlertDialog.Builder(activity).setTitle("渲染方式")
                    .setSingleChoiceItems(renderNames, renderIndex,
                        (d, n) -> { prefs.edit().putInt("scale", renderModes[n]).apply(); d.dismiss(); show(); }).show();
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
                if (which == 3) activity.showOverlaySettings();
                if (which == 5) {
                    prefs.edit().putBoolean("widescreen", !widescreen()).apply();
                    Toast.makeText(activity, "画面比例将在重启游戏后生效", Toast.LENGTH_LONG).show();
                    show();
                }
                if (which == 7) new AlertDialog.Builder(activity).setTitle("屏幕刷新率请求")
                    .setSingleChoiceItems(new String[]{"60 Hz", "72 Hz", "90 Hz", "120 Hz"},
                        refreshRate() == 60 ? 0 : refreshRate() == 72 ? 1 : refreshRate() == 90 ? 2 : 3,
                        (d, n) -> { prefs.edit().putInt("refreshRate", new int[]{60, 72, 90, 120}[n]).apply(); d.dismiss(); show(); }).show();
                if (which == 8) {
                    final int[] caps = {60, 45, 40, 36, 30};
                    int selectedCap = 0;
                    for (int i = 0; i < caps.length; ++i) if (frameCap() == caps[i]) selectedCap = i;
                    new AlertDialog.Builder(activity).setTitle("游戏帧率上限")
                        .setSingleChoiceItems(new String[]{"60 fps", "45 fps", "40 fps", "36 fps", "30 fps"}, selectedCap,
                            (d, n) -> { prefs.edit().putInt("frameCap", caps[n])
                                .putInt("refreshRate", PresentationPolicy.refreshForCap(caps[n])).apply();
                                d.dismiss(); show(); }).show();
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
                    if (input == null) throw new IOException("无法读取驱动 ZIP");
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
                DriverLibrary.validate(staging, library);
                prefs.edit().putString("library", library).putString("driver", "drivers/" + staging.getName())
                    .putString("driverLabel", json.optString("name", library)).putBoolean("custom", true).commit();
                activity.runOnUiThread(() -> Toast.makeText(activity, "驱动已导入，重启后验证实际加载情况", Toast.LENGTH_LONG).show());
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
