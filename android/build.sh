#!/usr/bin/env bash
# Thin wrapper: hand every argument to tools/build_host.py and nothing else.
# It never copies *_new headers, never selects stub sources, never touches git.
set -euo pipefail

cd "$(dirname "$0")"

# Use a real Windows Python (isolated with -I). Override with PYTHON=...
# Default is the explicit Git Bash path (bare `python` is a Windows Store alias).
PYTHON="${PYTHON:-/c/Users/fengj/AppData/Local/Programs/Python/Python312/python.exe}"

# Git Bash would rewrite '/data/local/tmp/...' etc. into Windows paths before
# native Python sees them, breaking --sandbox-root. Disable MSYS arg conversion.
export MSYS2_ARG_CONV_EXCL='*'

exec "$PYTHON" -I tools/build_host.py "$@"
