package com.d3mobile.host;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.graphics.Insets;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;

/**
 * Minimal offline diagnostic shell for the recovered D3 host.
 *
 * This is a test harness, not a game launcher. It prepares the on-disk data
 * root, loads libd3host.so, and sends exactly one start request to the native
 * side. It does NOT claim the game runs: the native call is asynchronous, so
 * returning from it only means the request was handed off, not that startup
 * succeeded. The UI reports status; it never retries or restarts anything.
 *
 * The Java package is com.d3mobile.host on purpose, even though the APK is
 * installed as com.d3mobile.host.recovery: the native symbol is
 * Java_com_d3mobile_host_MainActivity_nativeStart(JNIEnv*,jobject,jstring),
 * so the declaring class must keep this exact package and name.
 */
public class MainActivity extends Activity {

    private static final String TAG = "D3Recovery";

    /*
     * Canonical app-private data root, as the package manager sees it:
     * /data/user/0/com.d3mobile.host.recovery (the same directory as
     * /data/data/com.d3mobile.host.recovery). getFilesDir() resolves to
     * <private root>/files, so the runtime data root prepared below is
     * /data/user/0/com.d3mobile.host.recovery/files/runtime, which is the
     * profile the host is compiled against (D3_PRIVATE_ROOT / D3_DATA_ROOT).
     */
    private static final String PRIVATE_ROOT = "/data/user/0/com.d3mobile.host.recovery";

    private TextView statusView;
    private Button startButton;

    /** Guards the start button so the native request is only ever sent once. */
    private volatile boolean started = false;

    private native void nativeStart(String path);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Log.i(TAG, "onCreate entry pkg=" + getPackageName() + " privateRoot=" + PRIVATE_ROOT);

        setContentView(buildUi());
        WindowInsetsController bars = getWindow().getInsetsController();
        if (bars != null) {
            int lightBars = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                    | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            bars.setSystemBarsAppearance(lightBars, lightBars);
        }
        logBuildInfo();

        startButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onStartClicked();
            }
        });

        Intent intent = getIntent();
        boolean autostart = intent != null && intent.getBooleanExtra("autostart", false);
        if (autostart) {
            // ADB-driven: "am start ... --ez autostart true" fires the same path
            // as a tap. Still exactly one attempt.
            Log.i(TAG, "autostart=true; triggering the start button via performClick()");
            startButton.performClick();
        } else {
            setStatus("就绪。点击“启动兼容层”发送一次启动请求（不会自动开始）。");
        }
    }

    private View buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);
        root.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override
            public WindowInsets onApplyWindowInsets(View view, WindowInsets insets) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars()
                        | WindowInsets.Type.displayCutout());
                view.setPadding(pad + bars.left, pad + bars.top,
                        pad + bars.right, pad + bars.bottom);
                return insets;
            }
        });

        TextView title = new TextView(this);
        title.setText("D3HOST Recovery（离线诊断）");
        title.setTextSize(20);
        root.addView(title);

        startButton = new Button(this);
        startButton.setText("启动兼容层");
        root.addView(startButton);

        ScrollView scroll = new ScrollView(this);
        statusView = new TextView(this);
        statusView.setTextSize(13);
        scroll.addView(statusView);

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        root.addView(scroll, lp);
        return root;
    }

    private void logBuildInfo() {
        String abi = (Build.SUPPORTED_ABIS != null && Build.SUPPORTED_ABIS.length > 0)
                ? Build.SUPPORTED_ABIS[0] : "?";
        Log.i(TAG, "build sdkInt=" + Build.VERSION.SDK_INT
                + " release=" + Build.VERSION.RELEASE
                + " abi=" + abi
                + " device=" + Build.DEVICE
                + " fingerprint=" + Build.FINGERPRINT);
    }

    /** Runs on the UI thread. Enforces a single attempt, then works off-thread. */
    private void onStartClicked() {
        if (started) {
            Log.w(TAG, "start already requested; ignoring repeat click");
            return;
        }
        started = true;
        startButton.setEnabled(false);
        setStatus("已发送启动请求，正在后台线程准备 data root 并加载 native…");

        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                doStart();
            }
        }, "d3host-start");
        t.setDaemon(true);
        t.start();
    }

    /** Runs on the background thread. Never loops or restarts on failure. */
    private void doStart() {
        Log.i(TAG, "background start thread entered");
        try {
            // 1. Prepare the runtime data root: <filesDir>/runtime/logs, i.e.
            //    /data/user/0/com.d3mobile.host.recovery/files/runtime/logs.
            File filesDir = getFilesDir();
            File runtimeDir = new File(filesDir, "runtime");
            File logsDir = new File(runtimeDir, "logs");
            boolean madeRuntime = runtimeDir.mkdirs();
            boolean madeLogs = logsDir.mkdirs();
            Log.i(TAG, "data root runtime=" + runtimeDir.getAbsolutePath()
                    + " mkdirs=" + madeRuntime
                    + " logs=" + logsDir.getAbsolutePath()
                    + " mkdirs=" + madeLogs);
            if (!runtimeDir.isDirectory() || !logsDir.isDirectory()) {
                throw new IllegalStateException(
                        "failed to create runtime/logs under " + filesDir);
            }
            appendStatus("data root 就绪: " + runtimeDir.getAbsolutePath());

            // 2. Guest payload path, next to the extracted host library.
            String guestPath = getApplicationInfo().nativeLibraryDir + "/libd3guest.so";
            File guestFile = new File(guestPath);
            boolean guestExists = guestFile.isFile();
            long guestSize = guestExists ? guestFile.length() : -1L;
            Log.i(TAG, "guest=" + guestPath + " exists=" + guestExists + " size=" + guestSize);
            if (guestExists) {
                appendStatus("guest 文件存在 (" + guestSize + " bytes)");
            } else {
                throw new IllegalStateException("guest 文件缺失: " + guestPath);
            }

            // 3. Load the host library (libd3host.so from nativeLibraryDir).
            Log.i(TAG, "loading libd3host.so via System.loadLibrary(\"d3host\")");
            System.loadLibrary("d3host");
            Log.i(TAG, "libd3host.so loaded");

            // 4. Send the start request. nativeStart is asynchronous: a normal
            //    return means the request was accepted, NOT that the guest
            //    finished starting. Native failures (including assertions)
            //    surface through the native side and are not hidden here.
            Log.i(TAG, "calling nativeStart(" + guestPath + ") - async; return != completion");
            nativeStart(guestPath);
            Log.i(TAG, "nativeStart returned (request sent; completion pending, see logcat)");
            appendStatus("启动请求已发送。nativeStart 返回只代表请求已提交，不代表启动完成。");
        } catch (Throwable t) {
            // Report loudly, do not retry, do not loop-restart.
            Log.e(TAG, "start request failed", t);
            appendStatus("启动失败: " + t.getClass().getSimpleName() + ": " + t.getMessage());
        }
    }

    private void setStatus(final String msg) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                statusView.setText(msg);
            }
        });
    }

    private void appendStatus(final String msg) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                statusView.append(msg + "\n");
            }
        });
    }
}
