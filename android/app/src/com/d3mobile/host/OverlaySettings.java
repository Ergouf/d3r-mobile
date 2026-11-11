package com.d3mobile.host;

import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

final class OverlaySettings {
    private final MainActivity activity;
    private final GameControlsView controls;
    private final SharedPreferences prefs;

    OverlaySettings(MainActivity activity, GameControlsView controls) {
        this.activity = activity;
        this.controls = controls;
        prefs = activity.getSharedPreferences("overlay", 0);
        apply();
    }

    private int pixels(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private void apply() {
        controls.configureOverlay(prefs.getBoolean("controlsVisible", true),
            prefs.getInt("leftHorizontal", 0), prefs.getInt("leftVertical", 0),
            prefs.getBoolean("floatingMovement", true), prefs.getInt("movementWidth", 42), prefs.getInt("movementHeight", 60));
    }

    void show() {
        controls.releaseAll();
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(pixels(20), pixels(8), pixels(20), pixels(8));
        addToggle(content, "显示虚拟手柄", "controlsVisible");
        addToggle(content, "浮动移动摇杆", "floatingMovement");
        TextView hint = new TextView(activity);
        hint.setText("隐藏后按系统返回键恢复。左侧安全区内落指生成摇杆，满速只需短行程；继续拖动时基座有限跟随，松手归零；按键区域优先。");
        hint.setPadding(0, pixels(8), 0, pixels(8));
        content.addView(hint);
        addSlider(content, "左侧移动区宽度（屏幕百分比）", "movementWidth", 28, 48, 42);
        addSlider(content, "左侧移动区高度（屏幕百分比）", "movementHeight", 40, 80, 60);
        addSlider(content, "左侧横向（负值靠左）", "leftHorizontal", -80, 100);
        addSlider(content, "左侧纵向（负值向上）", "leftVertical", -120, 40);
        ScrollView scroll = new ScrollView(activity);
        scroll.addView(content);
        new AlertDialog.Builder(activity).setTitle("虚拟手柄与界面").setView(scroll)
            .setPositiveButton("完成", null)
            .setNeutralButton("恢复默认", (dialog, which) -> {
                prefs.edit().clear().apply();
                apply();
            }).show();
    }

    private void addToggle(LinearLayout content, String label, String key) {
        Switch toggle = new Switch(activity);
        toggle.setText(label);
        toggle.setMinHeight(pixels(48));
        toggle.setChecked(prefs.getBoolean(key, true));
        toggle.setOnCheckedChangeListener((button, checked) -> {
            prefs.edit().putBoolean(key, checked).apply();
            apply();
            if (!checked) Toast.makeText(activity, "按系统返回键可打开设置恢复显示", Toast.LENGTH_SHORT).show();
        });
        content.addView(toggle);
    }

    private void addSlider(LinearLayout content, String title, String key, int minimum, int maximum) {
        addSlider(content, title, key, minimum, maximum, 0);
    }

    private void addSlider(LinearLayout content, String title, String key, int minimum, int maximum, int initial) {
        TextView label = new TextView(activity);
        label.setText(title + "：" + prefs.getInt(key, initial));
        content.addView(label);
        SeekBar slider = new SeekBar(activity);
        slider.setMax(maximum - minimum);
        slider.setProgress(prefs.getInt(key, initial) - minimum);
        slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                if (!fromUser) return;
                int value = progress + minimum;
                prefs.edit().putInt(key, value).apply();
                label.setText(title + "：" + value);
                apply();
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override public void onStopTrackingTouch(SeekBar seekBar) {}
        });
        content.addView(slider);
    }
}
