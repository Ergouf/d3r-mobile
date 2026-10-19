package com.d3mobile.host;

final class FloatingJoystick {
    private float minimumX, minimumY, maximumX, maximumY, radius = 1;
    private float centerX, centerY, horizontal, vertical;
    private int pointer = -1;

    void configure(float left, float top, float right, float bottom, float size) {
        minimumX = left; minimumY = top;
        maximumX = Math.max(left, right); maximumY = Math.max(top, bottom);
        radius = Math.max(1, size);
        release();
    }

    boolean begin(int identity, float x, float y) {
        if (pointer >= 0 || identity < 0 || x < minimumX || x > maximumX || y < minimumY || y > maximumY) return false;
        pointer = identity;
        centerX = x; centerY = y;
        horizontal = vertical = 0;
        return true;
    }

    void move(int identity, float x, float y) {
        if (identity != pointer || pointer < 0) return;
        float deltaX = x - centerX, deltaY = y - centerY;
        float distance = (float)Math.hypot(deltaX, deltaY);
        if (distance > radius) {
            float excess = distance - radius;
            centerX = Math.max(minimumX, Math.min(maximumX, centerX + deltaX / distance * excess));
            centerY = Math.max(minimumY, Math.min(maximumY, centerY + deltaY / distance * excess));
            deltaX = x - centerX; deltaY = y - centerY;
        }
        float divisor = Math.max(radius, (float)Math.hypot(deltaX, deltaY));
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
