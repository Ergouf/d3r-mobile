package com.d3mobile.host;

final class PresentationPolicy {
    private static final int TEXT_SAFE_SCALE = 10;
    private static final int LARGE_SCALE = 15;
    static final int SCENE_FSR = 75;
    static final int SCENE_4_5 = 80;
    static final int SCENE_5_8 = 625;
    static final int SCENE_7_8 = 875;
    static final int DEFAULT_SCALE = TEXT_SAFE_SCALE;
    static final int DEFAULT_FRAME_CAP = 45;
    static final int AUTO_REFRESH_RATE = 0;
    private static final int DEFAULT_GUEST_WIDTH = 1600;
    private static final int MIN_WIDESCREEN_GUEST_WIDTH = 1600;
    private static final int MAX_WIDESCREEN_GUEST_WIDTH = 4096;

    private PresentationPolicy() {
    }

    static int textSafeScale(int requested) {
        return isSceneScale(requested) ? requested
             : requested == LARGE_SCALE ? LARGE_SCALE : TEXT_SAFE_SCALE;
    }

    static boolean isSceneScale(int scale) {
        return scale == SCENE_FSR || scale == SCENE_4_5 || scale == SCENE_5_8 || scale == SCENE_7_8;
    }

    static int frameCap(int requested) {
        return requested == 30 || requested == 36 || requested == 40 || requested == 45 || requested == 60
                ? requested : DEFAULT_FRAME_CAP;
    }

    static int refreshRate(int requested) {
        return requested == 60 || requested == 72 || requested == 90 || requested == 120
                ? requested : AUTO_REFRESH_RATE;
    }

    static int guestWidth(int physicalWidth, int physicalHeight, boolean widescreen) {
        requirePositiveDimensions(physicalWidth, physicalHeight);
        if (!widescreen) {
            return DEFAULT_GUEST_WIDTH;
        }

        long longEdge = Math.max(physicalWidth, physicalHeight);
        long shortEdge = Math.min(physicalWidth, physicalHeight);
        long numerator = 900L * longEdge;
        long denominator = 8L * shortEdge;
        long roundedSteps = (numerator + denominator / 2L) / denominator;
        long roundedWidth = 8L * roundedSteps;
        return (int) Math.max(
                MIN_WIDESCREEN_GUEST_WIDTH,
                Math.min(MAX_WIDESCREEN_GUEST_WIDTH, roundedWidth));
    }

    static Size surfaceSize(
            int physicalWidth,
            int physicalHeight,
            int guestWidth,
            int requestedScale) {
        requirePositiveDimensions(physicalWidth, physicalHeight);
        if (guestWidth <= 0) {
            throw new IllegalArgumentException("guestWidth must be positive");
        }

        int scale = textSafeScale(requestedScale);
        if (isSceneScale(scale)) scale = TEXT_SAFE_SCALE;
        long longEdge = Math.max(physicalWidth, physicalHeight);
        long shortEdge = Math.min(physicalWidth, physicalHeight);
        long requestedWidth = (long) guestWidth * scale / 10L;
        long width = Math.min(longEdge, requestedWidth);
        long height = Math.max(1L, width * shortEdge / longEdge);

        return new Size((int) width, (int) height);
    }

    private static void requirePositiveDimensions(int physicalWidth, int physicalHeight) {
        if (physicalWidth <= 0 || physicalHeight <= 0) {
            throw new IllegalArgumentException("physical dimensions must be positive");
        }
    }

    static final class Size {
        final int width;
        final int height;

        Size(int width, int height) {
            this.width = width;
            this.height = height;
        }
    }
}
