package com.d3mobile.host;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.graphics.Insets;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.FrameLayout;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.media.AudioManager;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.widget.EditText;
import android.text.InputFilter;
import android.text.InputType;

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

    static {
        // The SurfaceView can be created before the start button runs, so the
        // native library has to be loadable from the very first callback.
        System.loadLibrary("d3host");
    }

    /*
     * Canonical app-private data root, as the package manager sees it:
     * /data/user/0/com.d3mobile.host.recovery (the same directory as
     * /data/data/com.d3mobile.host.recovery). getFilesDir() resolves to
     * <private root>/files, so the runtime data root prepared below is
     * /data/user/0/com.d3mobile.host.recovery/files/runtime, which is the
     * profile the host is compiled against (D3_PRIVATE_ROOT / D3_DATA_ROOT).
     */
    private String PRIVATE_ROOT;
    private GraphicsSettings graphics;

    private TextView statusView;
    private Button startButton;
    private GameControlsView controls;
    private AudioManager audioManager;
    private AudioFocusRequest audioFocus;
    private boolean foreground;

    /** Guards the start button so the native request is only ever sent once. */
    private volatile boolean started = false;

    private native void nativeStart(String path);
    private native void nativePresent(android.view.Surface surface);
    native void nativeInput(long buttons, int lx, int ly, int rx, int ry);
    private native void nativeAudioActive(boolean active);
    private native void nativeAttach();
    private native void nativeDetach();
    private native void nativeKeyboardReply(String text);
    private native int nativeConfigure(int scale, String libraries, String directory, String name);
    private native String nativePrivateRoot();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        nativeAttach();
        PRIVATE_ROOT = getDataDir().getAbsolutePath();
        if (!PRIVATE_ROOT.equals(nativePrivateRoot())) throw new IllegalStateException("APK 身份与原生数据目录不匹配，请重新构建对应版本");
        graphics = new GraphicsSettings(this);
        nativeConfigure(graphics.scale(), getApplicationInfo().nativeLibraryDir, graphics.driverDirectory(), graphics.driverName());
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setDecorFitsSystemWindows(false);
        getWindow().getAttributes().layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        audioManager = (AudioManager)getSystemService(AUDIO_SERVICE);
        audioFocus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_GAME)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setOnAudioFocusChangeListener(new AudioManager.OnAudioFocusChangeListener() {
                    @Override public void onAudioFocusChange(int change) {
                        nativeAudioActive(foreground && change == AudioManager.AUDIOFOCUS_GAIN);
                    }
                }).build();
        Log.i(TAG, "onCreate entry pkg=" + getPackageName() + " privateRoot=" + PRIVATE_ROOT);

        setContentView(buildUi());
        enterFullscreen();
        logBuildInfo();

        startButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                onStartClicked();
            }
        });

        Intent intent = getIntent();
        boolean autostart = intent == null || intent.getBooleanExtra("autostart", true);
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
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xff000000);
        statusView = new TextView(this);
        statusView.setTextSize(14);
        statusView.setTextColor(0xffead8b4);
        statusView.setPadding(24, 16, 24, 16);
        statusView.setVisibility(View.GONE);
        SurfaceView preview = new SurfaceView(this);
        // The guest renders 1600 x 900. Composite at the same horizontal
        // resolution and let Android scale the fullscreen layer to the panel.
        android.graphics.Point display = new android.graphics.Point();
        getWindowManager().getDefaultDisplay().getRealSize(display);
        int longEdge = Math.max(display.x, display.y), shortEdge = Math.min(display.x, display.y);
        int renderWidth = Math.min(graphics.scale() == 15 ? 2400 : 1600, longEdge);
        preview.getHolder().setFixedSize(renderWidth, Math.max(1, renderWidth * shortEdge / longEdge));
        preview.getHolder().addCallback(new SurfaceHolder.Callback() {
            @Override
            public void surfaceCreated(SurfaceHolder holder) {
                Log.i(TAG, "surfaceCreated; handing the window to the GPU bridge");
                nativePresent(holder.getSurface());
                holder.getSurface().setFrameRate(60f, android.view.Surface.FRAME_RATE_COMPATIBILITY_FIXED_SOURCE);
            }

            @Override
            public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {}

            @Override
            public void surfaceDestroyed(SurfaceHolder holder) { nativePresent(null); }
        });
        root.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        controls = new GameControlsView(this);
        root.addView(controls, new FrameLayout.LayoutParams(-1, -1));
        Button settings = new Button(this);
        settings.setText("画面"); settings.setAlpha(0.65f);
        settings.setOnClickListener(v -> { controls.releaseAll(); graphics.show(); });
        FrameLayout.LayoutParams settingsLayout = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.LEFT);
        settingsLayout.leftMargin = 16; settingsLayout.topMargin = 12;
        root.addView(settings, settingsLayout);
        root.addView(statusView, new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL));
        startButton = new Button(this);
        startButton.setText("启动游戏");
        startButton.setVisibility(View.GONE);
        root.addView(startButton, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER));
        return root;
    }

    private void enterFullscreen() {
        WindowInsetsController bars = getWindow().getInsetsController();
        if (bars != null) {
            bars.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            bars.hide(WindowInsets.Type.systemBars());
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == GraphicsSettings.IMPORT_DRIVER && result == RESULT_OK && data != null && data.getData() != null)
            graphics.importDriver(data.getData());
    }

    /** Called by the guest worker through JNI; all widgets stay on Android's UI thread. */
    private void showKeyboard(final String title, final String hint, final String initial,
                              final int minimum, final int maximum) {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                controls.releaseAll();
                final EditText text = new EditText(MainActivity.this);
                text.setSingleLine(true);
                text.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
                text.setFilters(new InputFilter[] {new InputFilter.LengthFilter(maximum)});
                text.setText(initial); text.setHint(hint); text.selectAll();
                final AlertDialog dialog = new AlertDialog.Builder(MainActivity.this)
                        .setTitle(title.length() > 0 ? title : "角色名称")
                        .setView(text).setPositiveButton("确定", null)
                        .setNegativeButton("取消", new DialogInterface.OnClickListener() {
                            @Override public void onClick(DialogInterface d, int which) { nativeKeyboardReply(null); }
                        }).setOnCancelListener(new DialogInterface.OnCancelListener() {
                            @Override public void onCancel(DialogInterface d) { nativeKeyboardReply(null); }
                        }).create();
                dialog.setOnShowListener(new DialogInterface.OnShowListener() {
                    @Override public void onShow(DialogInterface d) {
                        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(new View.OnClickListener() {
                            @Override public void onClick(View v) {
                                if (text.length() < minimum) { text.setError("至少输入 " + minimum + " 个字符"); return; }
                                nativeKeyboardReply(text.getText().toString());
                                dialog.dismiss(); enterFullscreen();
                            }
                        });
                        text.requestFocus();
                        dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
                    }
                });
                dialog.show();
            }
        });
    }

    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) enterFullscreen();
        else if (controls != null) controls.releaseAll();
    }

    @Override protected void onResume() {
        super.onResume();
        foreground = true;
        nativeAudioActive(audioManager.requestAudioFocus(audioFocus) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED);
        if (controls != null) controls.setActive(true);
        enterFullscreen();
    }

    @Override protected void onPause() {
        foreground = false;
        if (controls != null) controls.setActive(false);
        nativeAudioActive(false);
        audioManager.abandonAudioFocusRequest(audioFocus);
        super.onPause();
    }

    @Override protected void onDestroy() {
        nativeDetach();
        super.onDestroy();
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        return controls != null && controls.handleKey(event) || super.dispatchKeyEvent(event);
    }

    @Override public boolean onGenericMotionEvent(MotionEvent event) {
        return controls != null && controls.handleMotion(event) || super.onGenericMotionEvent(event);
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
