# Thin wrapper over build.sh. It carries no clang path, no object list and no
# header copies; build.sh -> tools/build_host.py own the source set and flags.
# Pass extra flags through BUILD_ARGS, e.g. make BUILD_ARGS="--sandbox-root /data/local/tmp/d3".
BUILD_ARGS ?=

.PHONY: all host tests

all: host

host:
	bash build.sh $(BUILD_ARGS)

tests:
	bash build.sh --build-tests $(BUILD_ARGS)
