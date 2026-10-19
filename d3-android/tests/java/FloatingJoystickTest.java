package com.d3mobile.host;

public final class FloatingJoystickTest {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void near(float actual, float expected) { check(Math.abs(actual - expected) < .001f); }

    public static void main(String[] arguments) {
        FloatingJoystick stick = new FloatingJoystick();
        stick.configure(100, 400, 900, 1000, 100);
        check(!stick.begin(1, 50, 600));
        check(!stick.begin(1, 500, 300));
        check(stick.begin(7, 300, 700));
        near(stick.horizontal(), 0); near(stick.vertical(), 0);
        near(stick.centerX(), 300); near(stick.centerY(), 700);
        check(!stick.begin(8, 500, 600));
        stick.move(8, 800, 900);
        near(stick.centerX(), 300); near(stick.horizontal(), 0);
        stick.move(7, 350, 700);
        near(stick.horizontal(), .5f); near(stick.vertical(), 0);
        stick.move(7, 500, 700);
        near(stick.centerX(), 400); near(stick.horizontal(), 1);
        stick.move(7, 1000, 1200);
        check(stick.centerX() <= 900 && stick.centerY() <= 1000);
        check(Math.hypot(stick.horizontal(), stick.vertical()) <= 1.001);
        stick.end(8); check(stick.active());
        stick.end(7); check(!stick.active());
        near(stick.horizontal(), 0); near(stick.vertical(), 0);
        check(stick.begin(2, 650, 850));
        near(stick.centerX(), 650); near(stick.centerY(), 850);
        stick.configure(10, 20, 30, 40, 5);
        check(!stick.active());
        near(stick.horizontal(), 0); near(stick.vertical(), 0);
        check(!stick.begin(-1, 20, 30));
        check(stick.begin(3, 20, 30));
        stick.move(3, 100, 30);
        near(stick.centerX(), 30); near(stick.centerY(), 30);
        near(stick.horizontal(), 1); near(stick.vertical(), 0);
        stick.release(); check(!stick.active());
        near(stick.horizontal(), 0); near(stick.vertical(), 0);
        check(stick.begin(4, 10, 20));
        near(stick.centerX(), 10); near(stick.centerY(), 20);
        System.out.println("Floating joystick ownership, zone, following, normalization and release passed");
    }
}
