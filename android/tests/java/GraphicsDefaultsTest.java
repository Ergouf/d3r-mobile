package com.d3mobile.host;

import android.content.SharedPreferences;
import java.io.File;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

public final class GraphicsDefaultsTest {
    public static void main(String[] args) throws Exception {
        File runtime = Files.createTempDirectory("graphics-defaults-test").toFile();
        File override = new File(runtime, "profile-frame-cap");
        try {
            FakePreferences fresh = new FakePreferences();
            check(GraphicsDefaults.migrate(fresh.prefs, runtime), "fresh migration runs");
            assertDefaults(fresh);

            FakePreferences existing = new FakePreferences();
            existing.values.put("scale", 80);
            existing.values.put("frameCap", 60);
            existing.values.put("refreshRate", 120);
            existing.values.put("scene80DefaultApplied", true);
            existing.values.put("driver", "mali/custom");
            existing.values.put("widescreen", true);
            Files.write(override.toPath(), new byte[]{'6', '0'});
            check(GraphicsDefaults.migrate(existing.prefs, runtime), "existing install migrates");
            assertDefaults(existing);
            check(!override.exists(), "stale frame cap override is removed");
            check("mali/custom".equals(existing.values.get("driver")), "driver is preserved");
            check(Boolean.TRUE.equals(existing.values.get("widescreen")), "widescreen is preserved");

            existing.values.put("scale", 15);
            existing.values.put("frameCap", 30);
            existing.values.put("refreshRate", 60);
            Files.write(override.toPath(), new byte[]{'3', '0'});
            check(!GraphicsDefaults.migrate(existing.prefs, runtime), "migration runs only once");
            check(existing.values.get("scale").equals(15), "later scale choice is retained");
            check(existing.values.get("frameCap").equals(30), "later frame cap choice is retained");
            check(existing.values.get("refreshRate").equals(60), "later refresh choice is retained");
            check(override.exists(), "later diagnostic override is retained");

            Files.delete(override.toPath());
            FakePreferences failed = new FakePreferences();
            failed.failCommit = true;
            try {
                GraphicsDefaults.migrate(failed.prefs, runtime);
                throw new AssertionError("failed preference commit must be reported");
            } catch (IllegalStateException expected) {
                check(!failed.values.containsKey("native45AutoRefreshApplied"), "failed migration can be retried");
            }
            System.out.println("GraphicsDefaultsTest: fresh, upgrade, repeat and failure cases passed");
        } finally {
            Files.deleteIfExists(override.toPath());
            Files.delete(runtime.toPath());
        }
    }

    private static void assertDefaults(FakePreferences prefs) {
        check(prefs.values.get("scale").equals(10), "native 1.0x scale");
        check(prefs.values.get("frameCap").equals(45), "45 fps cap");
        check(prefs.values.get("refreshRate").equals(0), "system controls refresh rate");
        check(Boolean.TRUE.equals(prefs.values.get("native45AutoRefreshApplied")), "migration recorded");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static final class FakePreferences implements InvocationHandler {
        final Map<String, Object> values = new HashMap<>();
        final Map<String, Object> pending = new HashMap<>();
        boolean failCommit;
        final SharedPreferences prefs = (SharedPreferences) Proxy.newProxyInstance(
                SharedPreferences.class.getClassLoader(), new Class<?>[]{SharedPreferences.class}, this);
        final SharedPreferences.Editor editor = (SharedPreferences.Editor) Proxy.newProxyInstance(
                SharedPreferences.Editor.class.getClassLoader(),
                new Class<?>[]{SharedPreferences.Editor.class}, this);

        @Override public Object invoke(Object proxy, Method method, Object[] args) {
            switch (method.getName()) {
                case "getBoolean": return values.getOrDefault(args[0], args[1]);
                case "edit": pending.clear(); return editor;
                case "putInt":
                case "putBoolean": pending.put((String) args[0], args[1]); return editor;
                case "commit":
                    if (failCommit) return false;
                    values.putAll(pending);
                    return true;
                default: throw new UnsupportedOperationException(method.getName());
            }
        }
    }
}
