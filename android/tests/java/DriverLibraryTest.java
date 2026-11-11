package com.d3mobile.host;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.stream.Stream;

public final class DriverLibraryTest {
    private static byte[] fixture(boolean module, boolean maliDependency) {
        ByteBuffer data = ByteBuffer.allocate(512).order(ByteOrder.LITTLE_ENDIAN);
        data.putInt(0, 0x464c457f);
        data.put(4, (byte)2); data.put(5, (byte)1);
        data.putShort(16, (short)3); data.putShort(18, (short)183);
        data.putLong(40, 64);
        data.putShort(58, (short)64); data.putShort(60, (short)4);
        byte[] strings = "\0HMI\0libc.so\0libGLES_mali.so\0".getBytes(StandardCharsets.UTF_8);
        data.position(320); data.put(strings);
        data.putInt(132, 3); data.putLong(152, 320); data.putLong(160, strings.length);
        data.putInt(196, 11); data.putLong(216, 384); data.putLong(224, 48);
        data.putInt(232, 1); data.putLong(248, 24);
        data.putInt(260, 6); data.putLong(280, 448); data.putLong(288, 48);
        data.putInt(296, 1); data.putLong(312, 16);
        data.putInt(408, module ? 1 : 0); data.put(412, (byte)0x11); data.putShort(414, (short)1);
        data.putLong(448, 1); data.putLong(456, maliDependency ? 13 : 5);
        return data.array();
    }

    private static void rejected(File directory, String library, String message) throws Exception {
        try {
            DriverLibrary.validate(directory, library);
            throw new AssertionError("Invalid driver was accepted");
        } catch (IOException error) {
            if (!error.getMessage().contains(message)) throw new AssertionError(error.getMessage());
        }
    }

    public static void main(String[] arguments) throws Exception {
        if (arguments.length == 2) {
            DriverLibrary.validate(new File(arguments[0]), arguments[1]);
            System.out.println("Driver accepted: " + arguments[1]);
            return;
        }
        Path directory = Files.createTempDirectory("d3-driver-test");
        try {
            Path turnip = directory.resolve("vulkan.adreno.so");
            Files.write(turnip, fixture(true, false));
            DriverLibrary.validate(directory.toFile(), turnip.getFileName().toString());
            Files.write(turnip, fixture(false, false));
            rejected(directory.toFile(), turnip.getFileName().toString(), "HMI");
            byte[] wrongArchitecture = fixture(true, false);
            wrongArchitecture[18] = 62;
            Files.write(turnip, wrongArchitecture);
            rejected(directory.toFile(), turnip.getFileName().toString(), "ARM64");
            Files.write(turnip, new byte[20]);
            rejected(directory.toFile(), turnip.getFileName().toString(), "大小无效");
            byte[] truncatedTable = fixture(true, false);
            ByteBuffer.wrap(truncatedTable).order(ByteOrder.LITTLE_ENDIAN).putLong(40, Long.MAX_VALUE);
            Files.write(turnip, truncatedTable);
            rejected(directory.toFile(), turnip.getFileName().toString(), "被截断");
            byte[] invalidString = fixture(true, false);
            ByteBuffer.wrap(invalidString).order(ByteOrder.LITTLE_ENDIAN).putLong(456, 9999);
            Files.write(turnip, invalidString);
            rejected(directory.toFile(), turnip.getFileName().toString(), "字符串索引");
            Path mali = directory.resolve("vulkan.mali.so");
            Files.write(mali, fixture(false, true));
            rejected(directory.toFile(), mali.getFileName().toString(), "libGLES_mali.so");
            Files.write(directory.resolve("libGLES_mali.so"), fixture(true, false));
            DriverLibrary.validate(directory.toFile(), mali.getFileName().toString());
            System.out.println("8 driver validation scenarios passed");
        } finally {
            try (Stream<Path> paths = Files.walk(directory)) {
                for (Path path : (Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
            }
        }
    }
}
