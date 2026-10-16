ANDROID_NDK ?= D:\workspace\Gdict\android_sdk\ndk\28.2.13676358
CLANG := $(ANDROID_NDK)\toolchains\llvm\prebuilt\windows-x86_64\bin\clang.cmd

# Target architecture and API level
TARGET := aarch64-linux-android21
OUT_DIR := out
OBJ_DIR := $(OUT_DIR)/obj

# Source files
SOURCES := host/d3_host.c host/d3_service.c host/d3_table.c
OBJECTS := $(SOURCES:%.c=$(OBJ_DIR)/%.o)

# Build flags
CFLAGS := -Wall -O2 -fPIC
LDFLAGS := -shared

# Output library
LIBRARY := $(OUT_DIR)/libd3host.so

all: $(LIBRARY)

$(LIBRARY): $(OBJECTS)
	@mkdir -p $(OUT_DIR)
	$(CLANG) --target=$(TARGET) $(LDFLAGS) -o $@ $^
	@echo "Built: $@"

$(OBJ_DIR)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CLANG) --target=$(TARGET) $(CFLAGS) -c -o $@ $<

clean:
	rm -rf $(OUT_DIR)

.PHONY: all clean
