package com.d3mobile.host;

final class FloatingJoystick {
    private static final float AXIS_RATIO = .6f;    // full deflection before the visual rim
    private static final float FOLLOW_RATIO = .75f; // max base travel from the touch-down point
    private float minimumX, minimumY, maximumX, maximumY, radius = 1;
    private float axisRadius = .6f, followLimit = .75f;
    private float anchorX, anchorY, centerX, centerY, horizontal, vertical;
    private int pointer = -1;

    void configure(float left, float top, float right, float bottom, float size) {
        minimumX = left; minimumY = top;
        maximumX = Math.max(left, right); maximumY = Math.max(top, bottom);
        radius = Math.max(1, size);
        axisRadius = radius * AXIS_RATIO;
        followLimit = radius * FOLLOW_RATIO;
        release();
    }

    boolean begin(int identity, float x, float y) {
        if (pointer >= 0 || identity < 0 || x < minimumX || x > maximumX || y < minimumY || y > maximumY) return false;
        pointer = identity;
        anchorX = centerX = x; anchorY = centerY = y;
        horizontal = vertical = 0;
        return true;
    }

    /** Short throw + bounded follow: full speed at 0.6R, base never travels more than 0.75R. */
    void move(int identity, float x, float y) {
        if (identity != pointer || pointer < 0) return;
        float deltaX = x - centerX, deltaY = y - centerY;
        float distance = (float)Math.hypot(deltaX, deltaY);
        if (distance > axisRadius) {
            float excess = distance - axisRadius;
            float nextX = centerX + deltaX / distance * excess;
            float nextY = centerY + deltaY / distance * excess;
            nextX = Math.max(anchorX - followLimit, Math.min(anchorX + followLimit, nextX));
            nextY = Math.max(anchorY - followLimit, Math.min(anchorY + followLimit, nextY));
            centerX = Math.max(minimumX, Math.min(maximumX, nextX));
            centerY = Math.max(minimumY, Math.min(maximumY, nextY));
            deltaX = x - centerX; deltaY = y - centerY;
        }
        float divisor = Math.max(axisRadius, (float)Math.hypot(deltaX, deltaY));
        horizontal = deltaX / divisor; vertical = deltaY / divisor;
    }

    void end(int identity) { if (identity == pointer) release(); }
    void release() { pointer = -1; horizontal = vertical = 0; }
    boolean active() { return pointer >= 0; }
    float centerX() { return centerX; }
    float centerY() { return centerY; }
    float horizontal() { return horizontal; }
    float vertical() { return vertical; }
}
