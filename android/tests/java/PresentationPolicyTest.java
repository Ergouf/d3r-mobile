package com.d3mobile.host;

public final class PresentationPolicyTest {
    public static void main(String[] args) {
        testTextSafeScale();
        testFrameCaps();
        testGuestWidth();
        testSurfaceSize();
        testPhysicalDimensionBoundaries();
        System.out.println("PresentationPolicyTest: all assertions passed");
    }

    private static void testTextSafeScale() {
        assertEquals(10, PresentationPolicy.DEFAULT_SCALE, "fresh installs default to native 1.0x rendering");
        assertEquals(10, PresentationPolicy.textSafeScale(7), "0.75 sentinel becomes safe 1.0x");
        assertEquals(10, PresentationPolicy.textSafeScale(10), "1.0x remains 1.0x");
        assertEquals(15, PresentationPolicy.textSafeScale(15), "1.5x remains 1.5x");
        assertEquals(75, PresentationPolicy.textSafeScale(75), "separate scene FSR mode survives normalization");
        assertEquals(80, PresentationPolicy.textSafeScale(80), "80% scene mode survives normalization");
        assertEquals(625, PresentationPolicy.textSafeScale(625), "62.5% scene mode survives normalization");
        assertEquals(875, PresentationPolicy.textSafeScale(875), "87.5% scene mode survives normalization");
        assertEquals(10, PresentationPolicy.textSafeScale(0), "zero scale falls back to 1.0x");
        assertEquals(10, PresentationPolicy.textSafeScale(-1), "negative scale falls back to 1.0x");
        assertEquals(10, PresentationPolicy.textSafeScale(Integer.MAX_VALUE),
                "unknown large scale falls back to 1.0x");
    }

    private static void testGuestWidth() {
        assertEquals(2000, PresentationPolicy.guestWidth(2800, 1260, true),
                "widescreen guest follows long-edge formula");
        assertEquals(2000, PresentationPolicy.guestWidth(1260, 2800, true),
                "landscape and portrait use the same long edge");
        assertEquals(1600, PresentationPolicy.guestWidth(3840, 2160, true),
                "16:9 guest width");
        assertEquals(4096, PresentationPolicy.guestWidth(5000, 900, true),
                "widescreen guest is capped");
        assertEquals(1600, PresentationPolicy.guestWidth(1000, 1000, true),
                "near-square input is floored");
        assertEquals(1600, PresentationPolicy.guestWidth(2800, 1260, false),
                "non-widescreen uses default guest width");
        assertEquals(4096, PresentationPolicy.guestWidth(Integer.MAX_VALUE, 1, true),
                "extreme landscape ratio cannot overflow");
        assertEquals(4096, PresentationPolicy.guestWidth(1, Integer.MAX_VALUE, true),
                "extreme portrait ratio cannot overflow");
    }

    private static void testSurfaceSize() {
        for (int mode : new int[]{625, 75, 80, 875}) {
            assertSize(2000, 900, PresentationPolicy.surfaceSize(2800, 1260, 2000, mode),
                    "all scene scales preserve native UI surface " + mode);
        }
        assertSize(2000, 900, PresentationPolicy.surfaceSize(2800, 1260, 2000, 75),
                "scene FSR keeps the UI and swapchain at native logical size");
        assertSize(2000, 900, PresentationPolicy.surfaceSize(2800, 1260, 2000, 7),
                "0.75 sentinel renders at safe 1.0x without intermediate downsampling");
        assertSize(2000, 900, PresentationPolicy.surfaceSize(2800, 1260, 2000, 10),
                "1.0x uses the full logical guest surface");
        assertSize(2800, 1260, PresentationPolicy.surfaceSize(2800, 1260, 2000, 15),
                "1.5x is constrained by the physical screen");
        assertSize(2000, 900, PresentationPolicy.surfaceSize(1260, 2800, 2000, 10),
                "portrait input matches landscape output");
        assertSize(2800, 1260, PresentationPolicy.surfaceSize(1260, 2800, 2000, 15),
                "portrait 1.5x input matches landscape output");
        assertSize(1600, 1000, PresentationPolicy.surfaceSize(2560, 1600, 1600, 10),
                "16:10 surface preserves aspect ratio and lets the game letterbox");
        assertSize(1600, 1000, PresentationPolicy.surfaceSize(1600, 2560, 1600, 10),
                "rotated 16:10 surface preserves aspect ratio");
        assertSize(1280, 720, PresentationPolicy.surfaceSize(1280, 720, 2000, 10),
                "guest larger than physical screen is constrained naturally");
        assertSize(2000, 1,
                PresentationPolicy.surfaceSize(1, Integer.MAX_VALUE, 2000, 10),
                "extreme portrait output uses long arithmetic");
        assertSize(2000, 1,
                PresentationPolicy.surfaceSize(Integer.MAX_VALUE, 1, 2000, 10),
                "extreme landscape output uses long arithmetic");
        assertSize(Integer.MAX_VALUE, 1,
                PresentationPolicy.surfaceSize(Integer.MAX_VALUE, 1, Integer.MAX_VALUE, 10),
                "maximum integer inputs remain valid");
    }

    private static void testFrameCaps() {
        for (int cap : new int[]{30, 36, 40, 45, 60}) {
            assertEquals(cap, PresentationPolicy.frameCap(cap), "supported cap remains intact");
        }
        assertEquals(45, PresentationPolicy.DEFAULT_FRAME_CAP, "fresh installs default to 45 fps");
        assertEquals(45, PresentationPolicy.frameCap(0), "invalid cap defaults to 45");
        assertEquals(45, PresentationPolicy.frameCap(120), "unsupported cap defaults to 45");
        assertEquals(0, PresentationPolicy.refreshRate(0), "refresh defaults to system control");
        assertEquals(0, PresentationPolicy.refreshRate(-1), "invalid refresh falls back to system control");
        for (int rate : new int[]{60, 72, 90, 120}) {
            assertEquals(rate, PresentationPolicy.refreshRate(rate), "explicit refresh choice remains intact");
        }
    }

    private static void testPhysicalDimensionBoundaries() {
        expectIllegalArgument(() -> PresentationPolicy.guestWidth(0, 1080, true),
                "zero width rejected");
        expectIllegalArgument(() -> PresentationPolicy.guestWidth(1920, -1, true),
                "negative height rejected");
        expectIllegalArgument(() -> PresentationPolicy.surfaceSize(-1, 1080, 1600, 10),
                "surface zero/negative dimensions rejected");
        expectIllegalArgument(() -> PresentationPolicy.surfaceSize(1920, 1080, 0, 10),
                "zero guest width rejected");
        expectIllegalArgument(() -> PresentationPolicy.surfaceSize(1920, 1080, -1, 10),
                "negative guest width rejected");
    }

    private static void assertSize(int expectedWidth, int expectedHeight,
            PresentationPolicy.Size actual, String message) {
        assertEquals(expectedWidth, actual.width, message + " (width)");
        assertEquals(expectedHeight, actual.height, message + " (height)");
    }

    private static void assertEquals(int expected, int actual, String message) {
        if (expected != actual) {
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
        }
    }

    private static void expectIllegalArgument(Runnable action, String message) {
        try {
            action.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError(message);
    }
}
