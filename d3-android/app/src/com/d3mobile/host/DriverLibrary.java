package com.d3mobile.host;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

final class DriverLibrary {
    private final ByteBuffer data;
    private final List<String> dependencies = new ArrayList<>();
    private boolean hasSymbols, hasModule;

    private DriverLibrary(File file) throws IOException {
        if (file.length() < 64 || file.length() > 256L * 1024 * 1024)
            throw new IOException("驱动 ELF 大小无效：" + file.getName());
        data = ByteBuffer.wrap(Files.readAllBytes(file.toPath())).order(ByteOrder.LITTLE_ENDIAN);
        if (data.getInt(0) != 0x464c457f || data.get(4) != 2 || data.get(5) != 1
                || data.getShort(16) != 3 || data.getShort(18) != 183)
            throw new IOException("需要 ARM64 ELF 共享库：" + file.getName());
        long sections = data.getLong(40);
        int entrySize = Short.toUnsignedInt(data.getShort(58));
        int count = Short.toUnsignedInt(data.getShort(60));
        if (sections == 0 && count == 0) return;
        if (entrySize < 64 || count == 0) throw new IOException("驱动 ELF 节表无效");
        range(sections, (long)entrySize * count);
        for (int index = 0; index < count; index++) {
            int section = (int)(sections + (long)index * entrySize);
            int type = data.getInt(section + 4);
            if (type != 6 && type != 11) continue;
            long offset = data.getLong(section + 24);
            long length = data.getLong(section + 32);
            int stringIndex = data.getInt(section + 40);
            long stride = data.getLong(section + 56);
            if (stringIndex < 0 || stringIndex >= count || stride < (type == 6 ? 16 : 24)
                    || length < 0 || length % stride != 0) throw new IOException("驱动 ELF 动态表无效");
            range(offset, length);
            int strings = (int)(sections + (long)stringIndex * entrySize);
            long stringOffset = data.getLong(strings + 24);
            long stringLength = data.getLong(strings + 32);
            range(stringOffset, stringLength);
            if (type == 11) hasSymbols = true;
            for (long cursor = offset; cursor < offset + length; cursor += stride) {
                if (type == 6) {
                    long tag = data.getLong((int)cursor);
                    if (tag == 0) break;
                    if (tag == 1) dependencies.add(string(stringOffset, stringLength, data.getLong((int)cursor + 8)));
                } else if (data.getShort((int)cursor + 6) != 0) {
                    int info = Byte.toUnsignedInt(data.get((int)cursor + 4));
                    int visibility = data.get((int)cursor + 5) & 3;
                    if ((info >>> 4) != 0 && visibility != 1 && visibility != 2
                            && string(stringOffset, stringLength, Integer.toUnsignedLong(data.getInt((int)cursor))).equals("HMI"))
                        hasModule = true;
                }
            }
        }
    }

    private void range(long offset, long length) throws IOException {
        if (offset < 0 || length < 0 || offset > data.limit() || length > data.limit() - offset)
            throw new IOException("驱动 ELF 数据被截断");
    }

    private String string(long offset, long length, long index) throws IOException {
        if (index < 0 || index >= length) throw new IOException("驱动 ELF 字符串索引无效");
        int start = (int)(offset + index), end = start;
        while (end < offset + length && data.get(end) != 0) end++;
        if (end == offset + length) throw new IOException("驱动 ELF 字符串被截断");
        return new String(data.array(), start, end - start, StandardCharsets.UTF_8);
    }

    static void validate(File directory, String library) throws IOException {
        DriverLibrary primary = new DriverLibrary(new File(directory, library));
        boolean mali = library.equals("vulkan.mali.so") || primary.dependencies.contains("libGLES_mali.so");
        if (mali && primary.dependencies.contains("libGLES_mali.so")) {
            File dependency = new File(directory, "libGLES_mali.so");
            if (!dependency.isFile()) throw new IOException(
                "Mali 驱动包不完整：" + library + " 依赖 libGLES_mali.so，但 ZIP 未包含该库。"
                + "此包不能作为独立自定义驱动启用，当前驱动设置保持不变。请提供完整且适配本机 GPU 的驱动包。");
            DriverLibrary implementation = new DriverLibrary(dependency);
            primary.hasModule |= implementation.hasModule;
            primary.hasSymbols &= implementation.hasSymbols;
        }
        if (primary.hasSymbols && !primary.hasModule)
            throw new IOException("驱动缺少 Android Vulkan HAL 入口 HMI，不能使用该驱动包");
    }
}
