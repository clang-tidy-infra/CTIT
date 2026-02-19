#!/bin/bash
set -euo pipefail

CHECK_NAME="${1:-""}"

if [ -z "$CHECK_NAME" ]; then
    echo "Error: Check name is required."
    echo "Usage: $0 <check_name>"
    exit 1
fi

ROOT_DIR=$(pwd)
SOURCE_DIR="$ROOT_DIR/test-projects/cppcheck"
BUILD_DIR="$SOURCE_DIR/build"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/cppcheck.log"
CLANG_TIDY_BIN="$ROOT_DIR/llvm-project/build/bin/clang-tidy"
RUN_TIDY_SCRIPT="$ROOT_DIR/llvm-project/clang-tools-extra/clang-tidy/tool/run-clang-tidy.py"

echo "[Cppcheck] Starting integration test for check: $CHECK_NAME"

mkdir -p "$LOG_DIR"

echo "[Cppcheck] Removing existing .clang-tidy files..."
find "$SOURCE_DIR" -name ".clang-tidy" -delete

if [ ! -f "$CLANG_TIDY_BIN" ]; then
    echo "Error: clang-tidy binary not found at $CLANG_TIDY_BIN"
    exit 1
fi

if [ ! -f "$RUN_TIDY_SCRIPT" ]; then
    echo "Error: run-clang-tidy.py not found at $RUN_TIDY_SCRIPT"
    exit 1
fi

echo "[Cppcheck] Configuring CMake..."
mkdir -p "$BUILD_DIR"
cmake -S "$SOURCE_DIR" \
      -B "$BUILD_DIR" \
      -G "Ninja" \
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTS=ON

echo "[Cppcheck] Running Pre-build..."
cmake --build "$BUILD_DIR" -j "$(nproc)"
echo "[Cppcheck] Running clang-tidy..."
TIDY_ARGS=("-clang-tidy-binary" "$CLANG_TIDY_BIN" "-p" "$BUILD_DIR" "-checks=-*,$CHECK_NAME" "-quiet")
if [ -n "${TIDY_CONFIG:-}" ]; then
    TIDY_ARGS+=("-config=$TIDY_CONFIG")
fi

python3 "$RUN_TIDY_SCRIPT" "${TIDY_ARGS[@]}" 2>&1 | tee "$LOG_FILE" || true

echo "[Cppcheck] Finished. Log saved to $LOG_FILE"
