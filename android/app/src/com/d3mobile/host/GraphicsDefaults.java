package com.d3mobile.host;

import android.content.SharedPreferences;
import java.io.File;

final class GraphicsDefaults {
    private static final String MIGRATED = "native45AutoRefreshApplied";

    private GraphicsDefaults() {}

    static boolean migrate(SharedPreferences prefs, File runtimeDir) {
        if (prefs.getBoolean(MIGRATED, false)) return false;

        // A stale diagnostic override takes precedence over the saved frame cap.
        File override = new File(runtimeDir, "profile-frame-cap");
        if (override.exists() && !override.delete()) {
            throw new IllegalStateException("Could not clear previous frame cap diagnostic override");
        }
        if (!prefs.edit().putInt("scale", PresentationPolicy.DEFAULT_SCALE)
                .putInt("frameCap", PresentationPolicy.DEFAULT_FRAME_CAP)
                .putInt("refreshRate", PresentationPolicy.AUTO_REFRESH_RATE)
                .putBoolean(MIGRATED, true).commit()) {
            throw new IllegalStateException("Could not save graphics defaults");
        }
        return true;
    }
}
