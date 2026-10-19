package com.d3mobile.host;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Insets;
import android.util.SparseArray;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowInsets;
import java.util.ArrayList;

/** Native multitouch controller. Positions use a 1280 x 720 landscape canvas. */
final class GameControlsView extends View {
    private final MainActivity activity;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final ArrayList<Control> buttons = new ArrayList<>();
    private final SparseArray<Control> touches = new SparseArray<>();
    private final Control left = new Control("移动", 150, 550, 91, -1);
    private final Control right = new Control("闪避 / 瞄准", 925, 563, 66, -2);
    private float scale = 1, ox, oy;
    private Insets safe = Insets.NONE;
    private long hardwareButtons;
    private int hlx, hly, hrx, hry;
    private boolean active;

    private static final class Control {
        final String label;
        final float x, y, radius;
        final int bit;
        int pointer = -1;
        float dx, dy;
        long pressedUntil;
        Control(String label, float x, float y, float radius, int bit) {
            this.label = label; this.x = x; this.y = y; this.radius = radius; this.bit = bit;
        }
        boolean contains(float px, float py) {
            return Math.hypot(px - x, py - y) <= radius + 8;
        }
    }

    GameControlsView(MainActivity activity) {
        super(activity);
        this.activity = activity;
        setFocusable(true);
        setContentDescription("游戏虚拟手柄：左摇杆移动，右摇杆闪避，右侧攻击与技能，顶部菜单");
        buttons.add(new Control("A", 1167, 575, 66, 0));
        buttons.add(new Control("B", 1050, 642, 42, 1));
        buttons.add(new Control("X", 1202, 452, 45, 2));
        buttons.add(new Control("Y", 1090, 436, 45, 3));
        buttons.add(new Control("L3", 65, 686, 25, 4));
        buttons.add(new Control("R3", 925, 686, 25, 5));
        buttons.add(new Control("L", 56, 330, 32, 6));
        buttons.add(new Control("R", 1025, 352, 35, 7));
        buttons.add(new Control("ZL", 139, 330, 34, 8));
        buttons.add(new Control("ZR", 1165, 334, 38, 9));
        buttons.add(new Control("+", 1200, 56, 30, 10));
        buttons.add(new Control("−", 1118, 56, 30, 11));
        buttons.add(new Control("◀", 302, 595, 27, 12));
        buttons.add(new Control("▲", 357, 540, 27, 13));
        buttons.add(new Control("▶", 412, 595, 27, 14));
        buttons.add(new Control("▼", 357, 650, 27, 15));
        setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View view, WindowInsets insets) {
                safe = insets.getInsets(WindowInsets.Type.displayCutout() | WindowInsets.Type.systemGestures());
                updateTransform();
                return insets;
            }
        });
    }

    private final Runnable sampler = new Runnable() {
        @Override public void run() {
            if (!active) return;
            publish();
            postDelayed(this, 8); // Hold states and sample numbers keep advancing at ~125 Hz.
        }
    };

    void setActive(boolean value) {
        active = value;
        removeCallbacks(sampler);
        if (value) post(sampler); else releaseAll();
    }

    void releaseAll() {
        touches.clear();
        left.pointer = right.pointer = -1;
        left.dx = left.dy = right.dx = right.dy = 0;
        for (Control b : buttons) { b.pointer = -1; b.pressedUntil = 0; }
        hardwareButtons = 0;
        hlx = hly = hrx = hry = 0;
        publish();
        invalidate();
    }

    private void updateTransform() {
        scale = Math.max(.01f, Math.min((getWidth() - safe.left - safe.right) / 1280f,
                (getHeight() - safe.top - safe.bottom) / 720f));
        ox = safe.left + (getWidth() - safe.left - safe.right - 1280 * scale) / 2;
        oy = safe.top + (getHeight() - safe.top - safe.bottom - 720 * scale) / 2;
        invalidate();
    }

    @Override protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        releaseAll();
        updateTransform();
    }

    private void publish() {
        long bits = hardwareButtons;
        final long now = SystemClock.uptimeMillis();
        for (Control b : buttons)
            if (b.pointer >= 0 || now < b.pressedUntil) bits |= 1L << b.bit;
        activity.nativeInput(bits,
                left.pointer >= 0 ? axis(left.dx) : hlx,
                left.pointer >= 0 ? axis(-left.dy) : hly,
                right.pointer >= 0 ? axis(right.dx) : hrx,
                right.pointer >= 0 ? axis(-right.dy) : hry);
    }

    private static int axis(float value) {
        float magnitude = Math.abs(value);
        if (magnitude < .12f) return 0;
        return (int)(Math.signum(value) * Math.min(1, (magnitude - .12f) / .88f) * 32767);
    }

    private void moveStick(Control c, float x, float y) {
        float dx = (x - c.x) / c.radius, dy = (y - c.y) / c.radius;
        float length = (float)Math.max(1, Math.hypot(dx, dy));
        c.dx = dx / length; c.dy = dy / length;
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
            releaseAll(); return true;
        }
        int action = event.getActionMasked(), index = event.getActionIndex();
        int id = event.getPointerId(index);
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            float x = (event.getX(index) - ox) / scale, y = (event.getY(index) - oy) / scale;
            Control selected = null;
            for (Control b : buttons) if (b.pointer < 0 && b.contains(x, y)) { selected = b; break; }
            if (selected == null && left.pointer < 0 && left.contains(x, y)) selected = left;
            if (selected == null && right.pointer < 0 && right.contains(x, y)) selected = right;
            if (selected != null) {
                selected.pointer = id; touches.put(id, selected);
                // Preserve a quick tap across at least one 30 Hz game poll.
                if (selected.bit >= 0) selected.pressedUntil = SystemClock.uptimeMillis() + 50;
            }
            getParent().requestDisallowInterceptTouchEvent(true);
        }
        for (int i = 0; i < event.getPointerCount(); i++) {
            Control c = touches.get(event.getPointerId(i));
            if (c != null && c.bit < 0) moveStick(c, (event.getX(i) - ox) / scale, (event.getY(i) - oy) / scale);
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
            Control c = touches.get(id);
            if (c != null) { c.pointer = -1; c.dx = c.dy = 0; touches.remove(id); }
            if (action == MotionEvent.ACTION_UP) performClick();
        }
        publish(); invalidate(); return true;
    }

    @Override public boolean performClick() { super.performClick(); return true; }

    @Override protected void onDraw(Canvas canvas) {
        canvas.save(); canvas.translate(ox, oy); canvas.scale(scale, scale);
        drawStick(canvas, left); drawStick(canvas, right);
        for (Control b : buttons) {
            boolean down = b.pointer >= 0 || (hardwareButtons & 1L << b.bit) != 0;
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(down ? 0xb8a17d42 : 0x62101820);
            canvas.drawCircle(b.x, b.y, b.radius, paint);
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(down ? 3 : 1.5f);
            paint.setColor(down ? 0xffffdf92 : 0x99c9b58b);
            canvas.drawCircle(b.x, b.y, b.radius - 1, paint);
            paint.setStyle(Paint.Style.FILL); paint.setTextAlign(Paint.Align.CENTER);
            paint.setTextSize(b.bit == 0 ? 32 : b.bit >= 12 ? 18 : 22);
            paint.setColor(0xeee8dfcd);
            canvas.drawText(b.label, b.x, b.y - (paint.ascent() + paint.descent()) / 2, paint);
        }
        canvas.restore();
    }

    private void drawStick(Canvas canvas, Control c) {
        paint.setStyle(Paint.Style.FILL); paint.setColor(0x40101820);
        canvas.drawCircle(c.x, c.y, c.radius, paint);
        paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(1.5f); paint.setColor(0x779db5bd);
        canvas.drawCircle(c.x, c.y, c.radius, paint);
        paint.setStyle(Paint.Style.FILL); paint.setColor(c.pointer >= 0 ? 0xaac6a56a : 0x669db5bd);
        canvas.drawCircle(c.x + c.dx * c.radius * .6f, c.y + c.dy * c.radius * .6f, c.radius * .38f, paint);
        paint.setColor(0x99eee1c4); paint.setTextSize(16); paint.setTextAlign(Paint.Align.CENTER);
        canvas.drawText(c.label, c.x, c.y + c.radius + 25, paint);
    }

    boolean handleKey(KeyEvent event) {
        int bit;
        switch (event.getKeyCode()) {
            case KeyEvent.KEYCODE_BUTTON_A: bit = 0; break;
            case KeyEvent.KEYCODE_BUTTON_B: bit = 1; break;
            case KeyEvent.KEYCODE_BUTTON_X: bit = 2; break;
            case KeyEvent.KEYCODE_BUTTON_Y: bit = 3; break;
            case KeyEvent.KEYCODE_BUTTON_THUMBL: bit = 4; break;
            case KeyEvent.KEYCODE_BUTTON_THUMBR: bit = 5; break;
            case KeyEvent.KEYCODE_BUTTON_L1: bit = 6; break;
            case KeyEvent.KEYCODE_BUTTON_R1: bit = 7; break;
            case KeyEvent.KEYCODE_BUTTON_L2: bit = 8; break;
            case KeyEvent.KEYCODE_BUTTON_R2: bit = 9; break;
            case KeyEvent.KEYCODE_BUTTON_START: bit = 10; break;
            case KeyEvent.KEYCODE_BUTTON_SELECT: bit = 11; break;
            case KeyEvent.KEYCODE_DPAD_LEFT: bit = 12; break;
            case KeyEvent.KEYCODE_DPAD_UP: bit = 13; break;
            case KeyEvent.KEYCODE_DPAD_RIGHT: bit = 14; break;
            case KeyEvent.KEYCODE_DPAD_DOWN: bit = 15; break;
            default: return false;
        }
        if (event.getAction() == KeyEvent.ACTION_DOWN) hardwareButtons |= 1L << bit;
        else if (event.getAction() == KeyEvent.ACTION_UP) hardwareButtons &= ~(1L << bit);
        publish(); invalidate(); return true;
    }

    boolean handleMotion(MotionEvent event) {
        if (!event.isFromSource(InputDevice.SOURCE_JOYSTICK)) return false;
        hlx = axis(event.getAxisValue(MotionEvent.AXIS_X));
        hly = axis(-event.getAxisValue(MotionEvent.AXIS_Y));
        hrx = axis(event.getAxisValue(MotionEvent.AXIS_Z));
        hry = axis(-event.getAxisValue(MotionEvent.AXIS_RZ));
        long mask = (1L << 8) | (1L << 9) | (15L << 12);
        hardwareButtons &= ~mask;
        if (event.getAxisValue(MotionEvent.AXIS_LTRIGGER) > .5f) hardwareButtons |= 1L << 8;
        if (event.getAxisValue(MotionEvent.AXIS_RTRIGGER) > .5f) hardwareButtons |= 1L << 9;
        float hx = event.getAxisValue(MotionEvent.AXIS_HAT_X), hy = event.getAxisValue(MotionEvent.AXIS_HAT_Y);
        if (hx < -.5f) hardwareButtons |= 1L << 12;
        if (hy < -.5f) hardwareButtons |= 1L << 13;
        if (hx > .5f) hardwareButtons |= 1L << 14;
        if (hy > .5f) hardwareButtons |= 1L << 15;
        publish(); return true;
    }
}
