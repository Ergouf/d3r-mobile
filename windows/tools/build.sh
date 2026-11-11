#!/usr/bin/env bash
set -euo pipefail
test "${MSYSTEM:-}" = CLANG64
cd "$(cygpath -u "$1")"
build_dir="$(cygpath -u "$3")"
if [[ "${2:-build}" == configure || ! -f "$build_dir/CMakeCache.txt" ]]; then
  cmake --preset default -B "$(cygpath -m "$build_dir")" \
    -DSNX_LLVM_CONFIG="$(cygpath -m "$(command -v llvm-config)")" \
    -DSNX_FFMPEG_SH="$(cygpath -m /usr/bin/sh.exe)" \
    -DSNX_FFMPEG_MAKE="$(cygpath -m /usr/bin/make.exe)" \
    -DPERL_EXECUTABLE="$(cygpath -m /usr/bin/perl.exe)" \
    -DSNX_OPENSSL_MAKE="$(cygpath -m /usr/bin/make.exe)" \
    -DCMAKE_DISABLE_FIND_PACKAGE_SDL3=ON
fi
cmake --build "$(cygpath -m "$build_dir")"
