package com.d3mobile.host;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Insets;
import android.graphics.Rect;
import android.util.SparseArray;
import android.util.Log;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.DisplayCutout;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowInsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Native multitouch controller. Logical positions use a uniform 1280 x 720 canvas. */
final class GameControlsView extends View {
    private final MainActivity activity;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final ArrayList<Control> buttons = new ArrayList<>();
    private final SparseArray<Control> touches = new SparseArray<>();
    private final Control left = new Control("移动", 150, 550, 91, -1);
    private final Control right = new Control("闪避 / 瞄准", 925, 563, 66, -2, true);
    private final FloatingJoystick floatingLeft = new FloatingJoystick();
    private boolean floatingMovement = true;
    private int movementWidth = 42, movementHeight = 60;
    private float scale = 1, ox, rx, oy;
    private Insets safe = Insets.NONE;
    private List<Rect> cutouts = Collections.emptyList();
    private float leftOffsetX, leftOffsetY;
    private float[] leftPosition = new float[2], leftShoulderPosition = new float[2];
    private float[] rightPosition = new float[2], rightShoulderPosition = new float[2];
    private long hardwareButtons;
    private int hlx, hly, hrx, hry;
    private boolean active;

    private static final class Control {
        final String label;
        final float x, y, radius;
        final int bit;
        final boolean rightSide;
        int pointer = -1;
        float dx, dy;
        long pressedUntil;
        Control(String label, float x, float y, float radius, int bit) {
            this(label, x, y, radius, bit, false);
        }
        Control(String label, float x, float y, float radius, int bit, boolean rightSide) {
            this.label = label; this.x = x; this.y = y; this.radius = radius; this.bit = bit;
            this.rightSide = rightSide;
        }
    }

    GameControlsView(MainActivity activity) {
        super(activity);
        this.activity = activity;
        setFocusable(true);
        setContentDescription("游戏虚拟手柄：左摇杆移动，右摇杆闪避，右侧攻击与技能，顶部菜单");
        buttons.add(new Control("A", 1167, 575, 66, 0, true));
        buttons.add(new Control("B", 1050, 642, 42, 1, true));
        buttons.add(new Control("X", 1202, 452, 45, 2, true));
        buttons.add(new Control("Y", 1090, 436, 45, 3, true));
        buttons.add(new Control("L3", 65, 686, 25, 4));
        buttons.add(new Control("R3", 925, 686, 25, 5, true));
        buttons.add(new Control("L", 56, 330, 32, 6));
        buttons.add(new Control("R", 1025, 352, 35, 7, true));
        buttons.add(new Control("ZL", 139, 330, 34, 8));
        buttons.add(new Control("ZR", 1165, 334, 38, 9, true));
        buttons.add(new Control("+", 1200, 56, 30, 10, true));
        buttons.add(new Control("−", 1118, 56, 30, 11, true));
        buttons.add(new Control("◀", 302, 595, 27, 12));
        buttons.add(new Control("▲", 357, 540, 27, 13));
        buttons.add(new Control("▶", 412, 595, 27, 14));
        buttons.add(new Control("▼", 357, 650, 27, 15));
        setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View view, WindowInsets insets) {
                DisplayCutout cutout = insets.getDisplayCutout();
                Insets waterfall = cutout == null ? Insets.NONE : cutout.getWaterfallInsets();
                safe = cutout == null ? waterfall : Insets.of(waterfall.left,
                    Math.max(waterfall.top, cutout.getSafeInsetTop()), waterfall.right,
                    Math.max(waterfall.bottom, cutout.getSafeInsetBottom()));
                cutouts = cutout == null ? Collections.emptyList() : cutout.getBoundingRects();
                releaseTouches();
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
        hardwareButtons = 0;
        hlx = hly = hrx = hry = 0;
        releaseTouches();
    }

    private void releaseTouches() {
        floatingLeft.release();
        touches.clear();
        left.pointer = right.pointer = -1;
        left.dx = left.dy = right.dx = right.dy = 0;
        for (Control b : buttons) { b.pointer = -1; b.pressedUntil = 0; }
        publish();
        invalidate();
    }

    void configureOverlay(boolean visible, int horizontal, int vertical, boolean floating, int widthPercent, int heightPercent) {
        releaseTouches();
        floatingMovement = floating;
        movementWidth = Math.max(28, Math.min(48, widthPercent));
        movementHeight = Math.max(40, Math.min(80, heightPercent));
        leftOffsetX = horizontal;
        leftOffsetY = vertical;
        setVisibility(visible ? View.VISIBLE : View.INVISIBLE);
        updateTransform();
    }

    private void updateTransform() {
        float w = Math.max(1, getWidth() - safe.left - safe.right);
        float h = Math.max(1, getHeight() - safe.top - safe.bottom);
        scale = Math.max(.01f, Math.min(w / 1280f, h / 720f));
        ox = safe.left;
        rx = getWidth() - safe.right - 1280f * scale;
        oy = safe.top + (h - 720f * scale) / 2f;
        leftPosition = placeGroup(false, false);
        leftShoulderPosition = placeGroup(false, true);
        rightPosition = placeGroup(true, false);
        rightShoulderPosition = placeGroup(true, true);
        float radius = screenR(left);
        float padding = 12 * getResources().getDisplayMetrics().density;
        floatingLeft.configure(safe.left + radius + padding,
            Math.max(safe.top + radius + padding, getHeight() * (1 - movementHeight / 100f)),
            Math.max(safe.left + radius + padding, getWidth() * movementWidth / 100f - radius),
            Math.max(safe.top + radius + padding, getHeight() - safe.bottom - radius - padding), radius);
        invalidate();
    }

    private boolean isShoulder(Control control) { return control.bit >= 6 && control.bit <= 9; }

    private float[] placeGroup(boolean rightSide, boolean shoulders) {
        ArrayList<Control> group = new ArrayList<>();
        if (!shoulders) group.add(rightSide ? right : left);
        for (Control button : buttons)
            if (button.rightSide == rightSide && isShoulder(button) == shoulders) group.add(button);
        float origin = rightSide ? rx : ox;
        float minX = Float.MAX_VALUE, minY = Float.MAX_VALUE, maxX = 0, maxY = 0;
        for (Control control : group) {
            minX = Math.min(minX, origin + (control.x - control.radius) * scale - 8);
            maxX = Math.max(maxX, origin + (control.x + control.radius) * scale + 8);
            minY = Math.min(minY, oy + (control.y - control.radius) * scale - 8);
            maxY = Math.max(maxY, oy + (control.y + control.radius) * scale + 8);
        }
        float horizontal = Math.max(safe.left - minX, Math.min(getWidth() - safe.right - maxX, rightSide ? 0 : leftOffsetX * scale));
        float vertical = Math.max(safe.top - minY, Math.min(getHeight() - safe.bottom - maxY, rightSide ? 0 : leftOffsetY * scale));
        for (Rect cutout : cutouts) {
            for (Control control : group) {
                float radius = screenR(control) + 8;
                float centerX = origin + control.x * scale + horizontal;
                float centerY = oy + control.y * scale + vertical;
                if (centerY + radius <= cutout.top || centerY - radius >= cutout.bottom
                        || centerX + radius <= cutout.left || centerX - radius >= cutout.right) continue;
                if (cutout.left == 0) horizontal += cutout.right - (centerX - radius);
                else if (cutout.right >= getWidth()) horizontal -= centerX + radius - cutout.left;
                else if (cutout.top == 0) vertical += cutout.bottom - (centerY - radius);
                else if (cutout.bottom >= getHeight()) vertical -= centerY + radius - cutout.top;
            }
        }
        return new float[]{horizontal, vertical};
    }

    private float screenX(Control c) {
        float[] position = c.rightSide ? (isShoulder(c) ? rightShoulderPosition : rightPosition)
            : (isShoulder(c) ? leftShoulderPosition : leftPosition);
        return (c.rightSide ? rx : ox) + c.x * scale + position[0];
    }
    private float screenY(Control c) {
        float[] position = c.rightSide ? (isShoulder(c) ? rightShoulderPosition : rightPosition)
            : (isShoulder(c) ? leftShoulderPosition : leftPosition);
        return oy + c.y * scale + position[1];
    }
    private float screenR(Control c) { return c.radius * scale; }

    int menuBottom() {
        float bottom = 0;
        for (Control control : buttons)
            if (control.bit == 10 || control.bit == 11) bottom = Math.max(bottom, screenY(control) + screenR(control));
        return (int)Math.ceil(bottom);
    }

    private boolean hit(Control c, float px, float py) {
        return Math.hypot(px - screenX(c), py - screenY(c)) <= screenR(c) + 8;
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
        if (c == left && floatingMovement) {
            floatingLeft.move(left.pointer, x, y);
            left.dx = floatingLeft.horizontal(); left.dy = floatingLeft.vertical();
            return;
        }
        float dx = (x - screenX(c)) / screenR(c), dy = (y - screenY(c)) / screenR(c);
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
            float x = event.getX(index), y = event.getY(index);
            Control selected = null;
            for (Control b : buttons) if (b.pointer < 0 && hit(b, x, y)) { selected = b; break; }
            if (selected == null && right.pointer < 0 && hit(right, x, y)) selected = right;
            if (selected == null && left.pointer < 0) {
                if (floatingMovement) {
                    boolean obstructed = false;
                    float radius = screenR(left) + 8;
                    for (Rect cutout : cutouts)
                        if (x + radius > cutout.left && x - radius < cutout.right
                                && y + radius > cutout.top && y - radius < cutout.bottom) obstructed = true;
                    if (!obstructed && floatingLeft.begin(id, x, y)) {
                        selected = left;
                        Log.i("d3input", "floating-start pointer=" + id + " center=" + x + "," + y);
                    }
                } else if (hit(left, x, y)) selected = left;
            }
            if (selected != null) {
                selected.pointer = id; touches.put(id, selected);
                // Preserve a quick tap across at least one 30 Hz game poll.
                if (selected.bit >= 0) selected.pressedUntil = SystemClock.uptimeMillis() + 50;
            }
            getParent().requestDisallowInterceptTouchEvent(true);
        }
        for (int i = 0; i < event.getPointerCount(); i++) {
            Control c = touches.get(event.getPointerId(i));
            if (c != null && c.bit < 0) moveStick(c, event.getX(i), event.getY(i));
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
            Control c = touches.get(id);
            if (c != null) {
                if (c == left) {
                    floatingLeft.end(id);
                    Log.i("d3input", "floating-release pointer=" + id + " axes=0,0");
                }
                c.pointer = -1; c.dx = c.dy = 0; touches.remove(id);
            }
            if (action == MotionEvent.ACTION_UP) performClick();
        }
        publish(); invalidate(); return true;
    }

    @Override public boolean performClick() { super.performClick(); return true; }

    @Override protected void onDraw(Canvas canvas) {
        drawStick(canvas, left); drawStick(canvas, right);
        for (Control b : buttons) {
            boolean down = b.pointer >= 0 || (hardwareButtons & 1L << b.bit) != 0;
            float cx = screenX(b), cy = screenY(b), r = screenR(b);
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(down ? 0xb8a17d42 : 0x62101820);
            canvas.drawCircle(cx, cy, r, paint);
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth((down ? 3 : 1.5f) * scale);
            paint.setColor(down ? 0xffffdf92 : 0x99c9b58b);
            canvas.drawCircle(cx, cy, Math.max(1, r - scale), paint);
            paint.setStyle(Paint.Style.FILL); paint.setTextAlign(Paint.Align.CENTER);
            paint.setTextSize((b.bit == 0 ? 32 : b.bit >= 12 ? 18 : 22) * scale);
            paint.setColor(0xeee8dfcd);
            canvas.drawText(b.label, cx, cy - (paint.ascent() + paint.descent()) / 2, paint);
        }
    }

    private void drawStick(Canvas canvas, Control c) {
        if (c == left && floatingMovement && !floatingLeft.active()) return;
        float cx = screenX(c), cy = screenY(c), r = screenR(c);
        if (c == left && floatingMovement) { cx = floatingLeft.centerX(); cy = floatingLeft.centerY(); }
        paint.setStyle(Paint.Style.FILL); paint.setColor(0x40101820);
        canvas.drawCircle(cx, cy, r, paint);
        paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(1.5f * scale); paint.setColor(0x779db5bd);
        canvas.drawCircle(cx, cy, r, paint);
        paint.setStyle(Paint.Style.FILL); paint.setColor(c.pointer >= 0 ? 0xaac6a56a : 0x669db5bd);
        canvas.drawCircle(cx + c.dx * r * .6f, cy + c.dy * r * .6f, r * .38f, paint);
        paint.setColor(0x99eee1c4); paint.setTextSize(16 * scale); paint.setTextAlign(Paint.Align.CENTER);
        canvas.drawText(c.label, cx, cy + r + 25 * scale, paint);
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
